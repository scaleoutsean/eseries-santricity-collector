#!/usr/bin/env python3
"""
Drive performance statistics enrichment processor for E-Series Performance Analyzer

This module provides enrichment for drive-level performance statistics by adding
drive configuration metadata as tags and fields for enhanced analytics and monitoring.
"""

import logging
from typing import Dict, List, Optional

from .system_cross_reference import SystemCrossReference
from .system_identification_helper import SystemIdentificationHelper

logger = logging.getLogger(__name__)

class DriveEnrichmentProcessor:
    """Processes drive performance enrichment with configuration data"""

    def __init__(self, system_enricher=None):
        self.drive_lookup = {}          # drive_id -> drive_config
        self.pool_lookup = {}           # pool_id -> pool_config
        self.system_lookup = {}         # system_id/system_wwn -> system_config
        self.controller_lookup = {}     # controller_id -> controller_config
        self.system_enricher = system_enricher  # Reference to main system enricher for shared cache

        # Centralized system cross-referencing
        self.system_cross_ref = SystemCrossReference()
        self.from_json = False  # Will be set by EnrichmentProcessor

        # Create shared system identification helper
        self.system_identifier = SystemIdentificationHelper(
            system_enricher
        )

    def set_json_mode(self, from_json: bool):
        """Update JSON mode setting for this enricher and its helper"""
        self.from_json = from_json
        if hasattr(self, 'system_identifier'):
            self.system_identifier.from_json = from_json

    def load_configuration_data(self,
                              drives: List[Dict],
                              storage_pools: List[Dict],
                              system_configs_data: Optional[List[Dict]] = None,
                              controllers: Optional[List[Dict]] = None):
        """Load drive configuration and storage pool data needed for enrichment"""

        # Build lookup tables
        self.drive_lookup = {d['id']: d for d in drives}
        # Also index by driveRef in case they differ
        for drive in drives:
            if drive.get('driveRef') and drive['driveRef'] != drive['id']:
                self.drive_lookup[drive['driveRef']] = drive

        self.pool_lookup = {p['id']: p for p in storage_pools}

        # Load controller configurations if provided
        self.controller_lookup = {}
        if controllers:
            # Handle multiple controllers with same ID (multi-system scenario)
            for controller in controllers:
                controller_id = controller.get('id') or controller.get('controller_id')
                if controller_id:
                    if controller_id not in self.controller_lookup:
                        self.controller_lookup[controller_id] = []
                    self.controller_lookup[controller_id].append(controller)

        # Load system configurations if provided
        self.system_lookup = {}
        if system_configs_data:
            # Handle both single system config dict and list of system configs
            if isinstance(system_configs_data, dict):
                system_configs_data = [system_configs_data]

            for system_config in system_configs_data:
                system_id = system_config.get('id')
                system_wwn = system_config.get('wwn')
                if system_id:
                    self.system_lookup[system_id] = system_config
                if system_wwn:
                    self.system_lookup[system_wwn] = system_config

        # Load into centralized cross-referencing utility
        if system_configs_data:
            self.system_cross_ref.load_system_configs(system_configs_data if isinstance(system_configs_data, list) else [system_configs_data])
        if controllers:
            self.system_cross_ref.load_controller_configs(controllers)

        logger.info(f"Loaded drive enrichment data: {len(drives)} drives, {len(storage_pools)} storage pools, {len(self.system_lookup)} systems")

    def _safe_get(self, obj, key, default=None):
        """Safely get a value from either a dict or a model object"""
        if isinstance(obj, dict):
            return obj.get(key, default)
        elif hasattr(obj, key):
            return getattr(obj, key, default)
        elif hasattr(obj, '_raw_data') and isinstance(obj._raw_data, dict):
            return obj._raw_data.get(key, default)
        else:
            return default

    def _safe_serialize_basemodel(self, obj):
        """Recursively serialize BaseModel objects to primitive types"""
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, dict):
            return {k: self._safe_serialize_basemodel(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._safe_serialize_basemodel(item) for item in obj]
        elif hasattr(obj, '__class__') and 'BaseModel' in str(obj.__class__.__mro__):
            # This is a BaseModel object, serialize it
            if hasattr(obj, 'model_dump'):
                return self._safe_serialize_basemodel(obj.model_dump())
            elif hasattr(obj, '_raw_data'):
                return self._safe_serialize_basemodel(obj._raw_data)
            elif hasattr(obj, '__dict__'):
                return self._safe_serialize_basemodel(obj.__dict__)
            else:
                return str(obj)
        else:
            # For other objects, try to convert to string as fallback
            return str(obj)

    def enrich_drive_performance(self, drive_performance) -> Dict:
        """Enrich a single drive performance measurement with configuration data"""

        disk_id = self._safe_get(drive_performance, 'diskId')
        if not disk_id:
            logger.warning("Drive performance record missing diskId")
            # Return as dict for consistency
            return drive_performance if isinstance(drive_performance, dict) else (drive_performance._raw_data if hasattr(drive_performance, '_raw_data') else {})

        # Get drive configuration
        drive_config = self.drive_lookup.get(disk_id)
        if not drive_config:
            logger.warning(f"Drive {disk_id} not found in configuration")
            # Return as dict for consistency
            return drive_performance if isinstance(drive_performance, dict) else (drive_performance._raw_data if hasattr(drive_performance, '_raw_data') else {})

        # Start with original performance data
        if isinstance(drive_performance, dict):
            enriched = drive_performance.copy()
        elif hasattr(drive_performance, '_raw_data'):
            # For model objects, start with raw data and ensure it's fully serialized
            raw_data = self._safe_serialize_basemodel(drive_performance._raw_data)
            enriched = raw_data if isinstance(raw_data, dict) else {}
        else:
            # Fallback: try to convert model to dict and serialize
            if hasattr(drive_performance, '__dict__'):
                dict_data = self._safe_serialize_basemodel(drive_performance.__dict__)
                enriched = dict_data if isinstance(dict_data, dict) else {}
            else:
                enriched = {}
                for field_name in dir(drive_performance):
                    if not field_name.startswith('_'):
                        value = getattr(drive_performance, field_name, None)
                        if not callable(value):
                            enriched[field_name] = self._safe_serialize_basemodel(value)

        # Ensure enriched is always a dictionary
        if not isinstance(enriched, dict):
            enriched = {}

        # Add tags
        enriched['tray_id'] = self._safe_get(drive_performance, 'trayId', 'unknown')

        # Get enhanced storage pool name from drive config -> storage pools lookup
        vol_group_ref = drive_config.get('currentVolumeGroupRef')
        pool = self.pool_lookup.get(vol_group_ref)
        if pool:
            enriched['vol_group_name'] = pool.get('name', 'unknown')
            enriched['pool_name'] = pool.get('name', 'unknown')  # Add pool_name field
        else:
            # Fallback to the volGroupName already in performance data
            enriched['vol_group_name'] = self._safe_get(drive_performance, 'volGroupName', 'unknown')
            enriched['pool_name'] = self._safe_get(drive_performance, 'volGroupName', 'unknown')  # Add pool_name fallback

        # Add fields (additional data points)
        enriched['has_degraded_channel'] = drive_config.get('hasDegradedChannel', False)

        # Use unified system identification
        fallback_configs = []
        if drive_config:
            fallback_configs.append(drive_config)
        if pool:
            fallback_configs.append(pool)

        system_config = self.system_identifier.get_system_config_for_performance_data(drive_performance)

        # DEBUG: Log the system identification process
        logger.debug(f"Drive enrichment for diskId {disk_id}: system_config found = {system_config is not None}")
        if drive_performance and isinstance(drive_performance, dict):
            logger.debug(f"Drive performance keys: {list(drive_performance.keys())[:10]}")
            logger.debug(f"Drive performance system_id: {drive_performance.get('system_id', 'MISSING')}")

        if system_config:
            # Apply system information from unified identification
            enriched['system_id'] = system_config.get('wwn')
            enriched['storage_system_name'] = system_config.get('name', 'unknown')
            enriched['storage_system_wwn'] = system_config.get('wwn', 'unknown')
        else:
            enriched['system_id'] = None
            enriched['storage_system_name'] = 'unknown'
            enriched['storage_system_wwn'] = 'unknown'

        # Add extended system information if available
        if system_config:
            try:
                system_tags = self.system_cross_ref.get_system_tags(system_config)
                enriched['system_model'] = system_tags.get('system_model')
                enriched['system_firmware_version'] = system_tags.get('system_firmware_version')
            except Exception as e:
                logger.debug(f"Could not extract extended system tags: {e}")
                enriched['system_model'] = None
                enriched['system_firmware_version'] = None
        else:
            enriched['system_model'] = None
            enriched['system_firmware_version'] = None

        # Add controller_unit tag based on controller_id from performance data
        # Note: Drives don't have a specific controllerId, and sourceController can change with connection shuffling
        # So we don't add controller_unit tag for drives to avoid confusion
        # controller_id = self._safe_get(drive_performance, 'sourceController')
        # if controller_id:
        #     enriched['controller_unit'] = self._get_controller_unit_from_id(controller_id)
        # else:
        #     enriched['controller_unit'] = 'unknown'

        # Optional: Add drive physical location info as tags
        physical_location = drive_config.get('physicalLocation', {})
        enriched['drive_slot'] = physical_location.get('slot', self._safe_get(drive_performance, 'driveSlot', 'unknown'))
        enriched['tray_ref'] = physical_location.get('trayRef', self._safe_get(drive_performance, 'trayRef', 'unknown'))

        # === ENHANCED DRIVE CHARACTERISTICS ===
        # Drive type and interface
        enriched['drive_type'] = drive_config.get('driveMediaType', 'unknown')  # SSD/HDD
        enriched['phy_drive_type'] = drive_config.get('phyDriveType', 'unknown')  # sas/sata/nvme

        # Interface type details
        interface_type = drive_config.get('interfaceType', {})
        if isinstance(interface_type, dict):
            enriched['interface_type'] = interface_type.get('driveType', 'unknown')
        else:
            enriched['interface_type'] = 'unknown'

        # Manufacturer and model information
        enriched['manufacturer'] = drive_config.get('manufacturer', 'unknown')
        enriched['product_id'] = drive_config.get('productID', 'unknown')
        enriched['serial_number'] = drive_config.get('serialNumber', 'unknown')
        enriched['firmware_version'] = drive_config.get('firmwareVersion', 'unknown')

        # Capacity information
        usable_capacity = drive_config.get('usableCapacity')
        if usable_capacity:
            try:
                capacity_gb = int(usable_capacity) // (1024**3)
                enriched['capacity_gb'] = capacity_gb
            except (ValueError, TypeError):
                enriched['capacity_gb'] = 0

        raw_capacity = drive_config.get('rawCapacity')
        if raw_capacity:
            try:
                raw_capacity_gb = int(raw_capacity) // (1024**3)
                enriched['raw_capacity_gb'] = raw_capacity_gb
            except (ValueError, TypeError):
                enriched['raw_capacity_gb'] = 0

        # Drive speed and performance characteristics
        enriched['current_speed'] = drive_config.get('currentSpeed', 'unknown')
        enriched['max_speed'] = drive_config.get('maxSpeed', 'unknown')
        enriched['spindle_speed'] = drive_config.get('spindleSpeed', 0)  # RPM for HDDs

        # === ENHANCED DRIVE STATUS AND HEALTH ===
        enriched['drive_status'] = drive_config.get('status', 'unknown')
        enriched['hot_spare'] = drive_config.get('hotSpare', False)
        enriched['pfa'] = drive_config.get('pfa', False)  # Predicted Failure Analysis
        enriched['uncertified'] = drive_config.get('uncertified', False)
        enriched['offline'] = drive_config.get('offline', False)
        enriched['available'] = drive_config.get('available', False)

        # Health status - preserve original status value
        status = drive_config.get('status', '').lower()
        if status:
            enriched['drive_status'] = status

        # === ENHANCED STORAGE POOL INFORMATION ===
        if pool:
            enriched['storage_pool_id'] = pool.get('id', 'unknown')
            enriched['pool_raid_level'] = pool.get('raidLevel', 'unknown')
            enriched['pool_status'] = pool.get('raidStatus', 'unknown')
            enriched['pool_state'] = pool.get('state', 'unknown')
            enriched['pool_usage'] = pool.get('usage', 'unknown')
            enriched['pool_security_type'] = pool.get('securityType', 'unknown')
        else:
            enriched['storage_pool_id'] = 'unknown'
            enriched['pool_raid_level'] = 'unknown'
            enriched['pool_status'] = 'unknown'
            enriched['pool_state'] = 'unknown'
            enriched['pool_usage'] = 'unknown'
            enriched['pool_security_type'] = 'unknown'

        # === ENHANCED USAGE AND SECURITY ===
        # Drive usage type
        if drive_config.get('hotSpare', False):
            enriched['drive_usage'] = 'hot_spare'
        else:
            enriched['drive_usage'] = 'data'

        # Protection and security
        enriched['protection_type'] = drive_config.get('protectionType', 'unknown')
        enriched['fde_enabled'] = drive_config.get('fdeEnabled', False)
        enriched['fde_capable'] = drive_config.get('fdeCapable', False)
        enriched['security_type'] = drive_config.get('driveSecurityType', 'unknown')

        # SSD-specific information
        ssd_wear_life = drive_config.get('ssdWearLife', {})
        if isinstance(ssd_wear_life, dict):
            enriched['ssd_wear_percent'] = ssd_wear_life.get('percentEnduranceUsed', 0)
            enriched['ssd_spare_blocks_percent'] = ssd_wear_life.get('spareBlocksRemainingPercent', 100)

        return enriched

    def _get_controller_unit_from_id(self, controller_id: str) -> str:
        """Get controller unit designation (A/B) based on controller ID."""
        if not controller_id or controller_id == 'unknown':
            return 'unknown'

        # Simple logic: controllers ending with '1' are A, '2' are B
        # This matches the logic used in controller performance enrichment
        if controller_id.endswith('1'):
            return 'A'
        elif controller_id.endswith('2'):
            return 'B'
        else:
            return 'unknown'

    def enrich_drive_performance_batch(self, drive_performances):
        """Enrich a batch of drive performance measurements"""

        enriched_results = []
        for perf_record in drive_performances:
            enriched = self.enrich_drive_performance(perf_record)
            enriched_results.append(enriched)

        logger.info(f"Enriched {len(enriched_results)} drive performance records")
        return enriched_results

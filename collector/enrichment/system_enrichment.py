#!/usr/bin/env python3
"""
System statistics enrichment processor for E-Series Performance Analyzer

This module provides enrichment for system-level performance statistics by adding
system configuration metadata as tags and fields for enhanced analytics and monitoring.
"""

import logging
from typing import List, Dict, Any, Optional
from .system_identification_helper import SystemIdentificationHelper

from .system_cross_reference import SystemCrossReference

LOG = logging.getLogger(__name__)

class SystemEnrichmentProcessor:
    """
    Enrichment processor for system performance statistics.

    Adds system configuration metadata to system performance metrics for better
    analytics and cross-system monitoring capabilities.
    """

    def __init__(self, system_enricher=None):
        """Initialize the system enrichment processor."""
        self.system_config_cache = None
        self.system_enricher = system_enricher
        self.system_identifier = SystemIdentificationHelper(system_enricher)
        self.system_cross_ref = SystemCrossReference()

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

        # Handle basic types
        if isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, (list, tuple)):
            return [self._safe_serialize_basemodel(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._safe_serialize_basemodel(v) for k, v in obj.items()}
        elif hasattr(obj, '__dict__'):
            # Handle BaseModel or other objects
            result = {}
            for key, value in obj.__dict__.items():
                if not key.startswith('_'):  # Skip private attributes
                    result[key] = self._safe_serialize_basemodel(value)
            return result
        else:
            return str(obj) if obj is not None else None

    def build_system_config_cache(self, system_configs: List[Dict[str, Any]]) -> None:
        """
        Build cache of system configuration data for enrichment.

        Args:
            system_configs: List of system configuration objects
        """
        self.system_config_cache.clear()

        for config in system_configs:
            if isinstance(config, dict):
                system_wwn = config.get('wwn')
                system_id = config.get('id')

                if system_wwn:
                    self.system_config_cache[system_wwn] = config
                    LOG.debug(f"Cached system config for WWN {system_wwn}: {config.get('name', 'Unknown')}")

                if system_id:
                    # Also cache by ID as fallback
                    self.system_config_cache[system_id] = config

        # Also load into SystemCrossReference for consistency
        self.system_cross_ref.load_system_configs(system_configs)

    def enrich_system_statistics(self, stats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich system performance statistics with configuration data.

        Args:
            stats: List of system performance statistics dictionaries

        Returns:
            List of enriched system statistics
        """
        if not stats:
            LOG.debug("No system statistics to enrich")
            return []

        LOG.debug(f"Starting enrichment for {len(stats)} system statistics")
        enriched_stats = []

        for stat in stats:
            # Handle both dict and Pydantic model objects
            if isinstance(stat, dict):
                enriched_stat = stat.copy()
            elif hasattr(stat, '_raw_data'):
                # For model objects, start with raw data and ensure it's fully serialized
                raw_data = self._safe_serialize_basemodel(stat._raw_data)
                enriched_stat = raw_data if isinstance(raw_data, dict) else {}
            else:
                # Fallback: try to convert model to dict and serialize
                if hasattr(stat, '__dict__'):
                    dict_data = self._safe_serialize_basemodel(stat.__dict__)
                    enriched_stat = dict_data if isinstance(dict_data, dict) else {}
                else:
                    enriched_stat = {}
                    for field_name in dir(stat):
                        if not field_name.startswith('_'):
                            value = getattr(stat, field_name, None)
                            if not callable(value):
                                enriched_stat[field_name] = self._safe_serialize_basemodel(value)

            # Get system information from shared cache using proper system identification
            system_config = None
            system_found = False

            # Extract system identification from the statistics data
            stat_system_wwn = self._safe_get(stat, 'storageSystemWWN') or self._safe_get(stat, 'system_id')

            # Try to find system config in cache by matching WWN
            if self.system_config_cache and stat_system_wwn:
                for cache_key, config in self.system_config_cache.items():
                    if isinstance(config, dict):
                        config_wwn = config.get('wwn')
                        if config_wwn and config_wwn == stat_system_wwn:
                            system_config = config
                            system_found = True
                            LOG.debug(f"Found matching system config in cache: key={cache_key}, wwn={config_wwn}")
                            break

                # Fallback: if no WWN match, use first available system config
                if not system_found:
                    for cache_key, config in self.system_config_cache.items():
                        if isinstance(config, dict):
                            system_config = config
                            system_found = True
                            LOG.debug(f"Using fallback system config from cache key: {cache_key}")
                            break

            if system_config and system_found:
                LOG.debug(f"Found system config - name={system_config.get('name')}, wwn={system_config.get('wwn')}")
                # Add core system identification (needed by InfluxDB writer)
                enriched_stat['storage_system_name'] = system_config.get('name', 'unknown')
                enriched_stat['storage_system_wwn'] = system_config.get('wwn', 'unknown')

                # Add system configuration tags for analytics
                enriched_stat.update({
                    # Core system identification tags
                    'system_name': system_config.get('name'),
                    'system_wwn': system_config.get('wwn'),
                    'system_model': system_config.get('model'),
                    'system_status': system_config.get('status'),
                    'system_sub_model': system_config.get('subModel'),

                    # System configuration tags
                    'firmware_version': system_config.get('fwVersion'),
                    'app_version': system_config.get('appVersion'),
                    'boot_version': system_config.get('bootVersion'),
                    'nvsram_version': system_config.get('nvsramVersion'),
                    'chassis_serial_number': system_config.get('chassisSerialNumber'),

                    # System capacity and hardware fields
                    'drive_count': system_config.get('driveCount'),
                    'tray_count': system_config.get('trayCount'),
                    'hot_spare_count': system_config.get('hotSpareCount'),
                    'used_pool_space': system_config.get('usedPoolSpace'),
                    'free_pool_space': system_config.get('freePoolSpace'),
                    'unconfigured_space': system_config.get('unconfiguredSpace'),

                    # System feature flags
                    'auto_load_balancing_enabled': system_config.get('autoLoadBalancingEnabled'),
                    'host_connectivity_reporting_enabled': system_config.get('hostConnectivityReportingEnabled'),
                    'remote_mirroring_enabled': system_config.get('remoteMirroringEnabled'),
                    'security_key_enabled': system_config.get('securityKeyEnabled'),
                    'simplex_mode_enabled': system_config.get('simplexModeEnabled'),

                    # Drive type information
                    'drive_types': ','.join(system_config.get('driveTypes', [])) if system_config.get('driveTypes') else None,
                })

                LOG.debug(f"Enriched system statistics with config metadata from {system_config.get('name')}")
            else:
                LOG.error(f"No system config found for system statistics - this indicates initialization failure")
                # System statistics require valid system config - fail rather than create unknown values
                raise ValueError("System statistics enrichment requires valid system configuration")

            enriched_stats.append(enriched_stat)

        LOG.info(f"Enriched {len(enriched_stats)} system statistics entries")
        return enriched_stats

    def get_enrichment_fields(self) -> List[str]:
        """
        Get list of fields added by this enrichment processor.

        Returns:
            List of field names added during enrichment
        """
        return [
            'system_name', 'system_wwn', 'system_model', 'system_status',
            'system_sub_model', 'firmware_version', 'app_version', 'boot_version',
            'nvsram_version', 'chassis_serial_number', 'drive_count', 'tray_count',
            'hot_spare_count', 'used_pool_space', 'free_pool_space', 'unconfigured_space',
            'auto_load_balancing_enabled', 'host_connectivity_reporting_enabled',
            'remote_mirroring_enabled', 'security_key_enabled', 'simplex_mode_enabled',
            'drive_types'
        ]

    def get_enrichment_tags(self) -> List[str]:
        """
        Get list of recommended tags from enriched fields for InfluxDB.

        Returns:
            List of field names that should be used as InfluxDB tags
        """
        return [
            'system_name', 'system_wwn', 'system_model', 'system_status',
            'firmware_version', 'chassis_serial_number', 'drive_types'
        ]

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

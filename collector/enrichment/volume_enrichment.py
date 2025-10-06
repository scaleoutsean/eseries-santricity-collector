"""
Volume Performance Enrichment

Enriches volume performance data with:
- host: Comma-separated list of host names mapped to the volume
- host_group: Host group name (single value or empty)
- storage_pool: Storage pool name where volume resides
- storage_system_name: Name of the storage system
- storage_system_wwn: WWN of the storage system
"""

from typing import Dict, List, Optional
import logging

from .system_cross_reference import SystemCrossReference
from .system_identification_helper import SystemIdentificationHelper

logger = logging.getLogger(__name__)

class VolumeEnrichmentProcessor:
    """Processes volume performance enrichment with host, host group, and storage pool information"""

    def __init__(self, system_enricher=None):
        self.host_lookup = {}           # host_id -> host_config
        self.hostgroup_lookup = {}      # hostgroup_id -> hostgroup_config
        self.pool_lookup = {}           # pool_id -> pool_config
        self.volume_lookup = {}         # volume_id -> volume_config
        self.volume_mappings = {}       # volume_id -> [mapping_configs]
        self.controller_lookup = {}     # controller_id -> controller_config

        # Centralized system cross-referencing
        self.system_cross_ref = SystemCrossReference()
        self.from_json = False  # Will be set by EnrichmentProcessor
        self.system_enricher = system_enricher  # Store reference for cache access

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
                              hosts: List[Dict],
                              host_groups: List[Dict],
                              storage_pools: List[Dict],
                              volumes: List[Dict],
                              volume_mappings: List[Dict],
                              system_configs: List[Dict],
                              controllers: Optional[List[Dict]] = None):
        """Load all configuration data needed for enrichment"""

        # Build lookup tables
        self.host_lookup = {h['id']: h for h in hosts}
        self.hostgroup_lookup = {hg['id']: hg for hg in host_groups}
        self.pool_lookup = {p['id']: p for p in storage_pools}
        self.volume_lookup = {v['id']: v for v in volumes}
        self.system_lookup = {s.get('wwn', s.get('storage_system_wwn', s.get('storageSystemWWN', s.get('storageSystemWwn', s.get('id'))))): s for s in system_configs}
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

        # Load into centralized cross-referencing utility
        if system_configs:
            self.system_cross_ref.load_system_configs(system_configs if isinstance(system_configs, list) else [system_configs])
        if controllers:
            self.system_cross_ref.load_controller_configs(controllers)

        # Group mappings by volume
        self.volume_mappings = {}
        for mapping in volume_mappings:
            vol_ref = mapping['volumeRef']
            if vol_ref not in self.volume_mappings:
                self.volume_mappings[vol_ref] = []
            self.volume_mappings[vol_ref].append(mapping)

        logger.info(f"Loaded enrichment data: {len(hosts)} hosts, {len(host_groups)} host groups, "
                   f"{len(storage_pools)} pools, {len(volumes)} volumes, {len(volume_mappings)} mappings, "
                   f"{len(system_configs)} systems, {len(self.controller_lookup)} controllers")

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

    def enrich_volume_performance(self, volume_performance) -> Dict:
        """Enrich a single volume performance measurement with host/pool tags"""

        volume_id = self._safe_get(volume_performance, 'volumeId')
        logger.debug(f"Volume enrichment starting - volume_id: {volume_id}, data_type: {type(volume_performance)}")

        if not volume_id:
            logger.warning("Volume performance record missing volumeId")
            return volume_performance

        # Get volume configuration
        volume = self.volume_lookup.get(volume_id)
        if not volume:
            logger.debug(f"Volume {volume_id} not found in configuration - using fallback enrichment")
            # Provide fallback enrichment for missing volumes
            return self._provide_fallback_volume_enrichment(volume_performance)
        else:
            logger.debug(f"Volume {volume_id} found in configuration - using full enrichment")

        # Get storage pool name
        pool_ref = volume.get('volumeGroupRef')
        pool = self.pool_lookup.get(pool_ref)
        pool_name = pool.get('name') if pool else 'unknown'

        # Use unified system identification
        system_config = self.system_identifier.get_system_config_for_performance_data(volume_performance)
        if system_config:
            system_name = system_config.get('name', 'unknown')
            system_wwn_tag = system_config.get('wwn', 'unknown')
        else:
            logger.warning("No system config found for volume performance data")
            system_name = 'unknown'
            system_wwn_tag = 'unknown'

        # Get mappings for this volume
        vol_mappings = self.volume_mappings.get(volume_id, [])

        # Build host and host group lists
        host_names = []
        host_group_names = set()

        for mapping in vol_mappings:
            map_ref = mapping['mapRef']
            mapping_type = mapping['type']

            if mapping_type == 'host':
                # Direct host mapping
                host = self.host_lookup.get(map_ref)
                if host:
                    host_name = host.get('label', host.get('name', 'unknown'))
                    host_names.append(host_name)
                    # Check if host is in a group
                    cluster_ref = host.get('clusterRef')
                    if cluster_ref:
                        hostgroup = self.hostgroup_lookup.get(cluster_ref)
                        if hostgroup:
                            host_group_names.add(hostgroup.get('name', 'unknown'))

            elif mapping_type == 'cluster':
                # Host group mapping - get all hosts in the group
                hostgroup = self.hostgroup_lookup.get(map_ref)
                if hostgroup:
                    host_group_names.add(hostgroup.get('name', 'unknown'))
                    # Find all hosts that are members of this group
                    for host_id, host in self.host_lookup.items():
                        if host.get('clusterRef') == map_ref:
                            host_name = host.get('label', host.get('name', 'unknown'))
                            host_names.append(host_name)

        # Build enrichment tags
        if isinstance(volume_performance, dict):
            enriched = volume_performance.copy()
        elif hasattr(volume_performance, '_raw_data'):
            # For model objects, start with raw data and ensure it's fully serialized
            raw_data = self._safe_serialize_basemodel(volume_performance._raw_data)
            enriched = raw_data if isinstance(raw_data, dict) else {}
        else:
            # Fallback: try to convert model to dict and serialize
            if hasattr(volume_performance, '__dict__'):
                dict_data = self._safe_serialize_basemodel(volume_performance.__dict__)
                enriched = dict_data if isinstance(dict_data, dict) else {}
            else:
                enriched = {}
                for field_name in dir(volume_performance):
                    if not field_name.startswith('_'):
                        value = getattr(volume_performance, field_name, None)
                        if not callable(value):
                            enriched[field_name] = self._safe_serialize_basemodel(value)

        # Ensure enriched is always a dictionary
        if not isinstance(enriched, dict):
            enriched = {}

        enriched['host'] = ','.join(sorted(set(host_names))) if host_names else ''
        enriched['host_group'] = ','.join(sorted(host_group_names)) if host_group_names else ''
        enriched['storage_pool'] = pool_name
        enriched['storage_system_name'] = system_name
        enriched['storage_system_wwn'] = system_wwn_tag

        # Add controller_unit tag based on controller_id from performance data
        controller_id = self._safe_get(volume_performance, 'controllerId')
        logger.debug(f"Volume enrichment - volume_id: {volume_id}, controller_id from performance: {controller_id}")
        if controller_id:
            controller_unit = self._get_controller_unit_from_id(controller_id)
            enriched['controller_unit'] = controller_unit
            logger.debug(f"Volume enrichment - mapped controller_id {controller_id} to controller_unit: {controller_unit}")
        else:
            enriched['controller_unit'] = 'unknown'
            logger.debug(f"Volume enrichment - no controller_id found, setting controller_unit to unknown")

        return enriched

    def _provide_fallback_volume_enrichment(self, volume_performance) -> Dict:
        """Provide basic enrichment for volumes not found in configuration"""

        logger.debug(f"Starting fallback enrichment for volume performance data type: {type(volume_performance)}")

        # Debug: Log available fields in volume performance data
        if isinstance(volume_performance, dict):
            logger.debug(f"Volume performance fields available: {list(volume_performance.keys())}")
        elif hasattr(volume_performance, '__dict__'):
            logger.debug(f"Volume performance attributes available: {list(volume_performance.__dict__.keys())}")

        # Start with original performance data
        if isinstance(volume_performance, dict):
            enriched = volume_performance.copy()
        elif hasattr(volume_performance, '_raw_data'):
            raw_data = self._safe_serialize_basemodel(volume_performance._raw_data)
            enriched = raw_data if isinstance(raw_data, dict) else {}
        else:
            enriched = {}
            for field_name in dir(volume_performance):
                if not field_name.startswith('_'):
                    value = getattr(volume_performance, field_name, None)
                    if not callable(value):
                        enriched[field_name] = self._safe_serialize_basemodel(value)

        # Ensure enriched is always a dictionary
        if not isinstance(enriched, dict):
            enriched = {}

        # Provide fallback values for missing volume data
        enriched['host'] = ''
        enriched['host_group'] = ''
        enriched['storage_pool'] = 'unknown'

        # Try to get controller unit from performance data
        controller_id = self._safe_get(volume_performance, 'controllerId')
        logger.debug(f"Fallback enrichment - volume_id: {self._safe_get(volume_performance, 'volumeId')}, controller_id from performance: {controller_id}")
        if controller_id:
            controller_unit = self._get_controller_unit_from_id(controller_id)
            enriched['controller_unit'] = controller_unit
            logger.debug(f"Fallback enrichment - mapped controller_id {controller_id} to controller_unit: {controller_unit}")
        else:
            enriched['controller_unit'] = 'unknown'
            logger.debug(f"Fallback enrichment - no controller_id found, setting controller_unit to unknown")

        # Use unified system identification for missing volumes
        system_config = self.system_identifier.get_system_config_for_performance_data(volume_performance)
        if system_config:
            enriched['storage_system_name'] = system_config.get('name', 'unknown')
            enriched['storage_system_wwn'] = system_config.get('wwn', 'unknown')
        else:
            enriched['storage_system_name'] = 'unknown'
            enriched['storage_system_wwn'] = 'unknown'

        logger.debug(f"Provided fallback enrichment for missing volume with controller_unit: {enriched['controller_unit']}")
        return enriched

    def enrich_volume_performance_batch(self, volume_performances):
        """Enrich a batch of volume performance measurements"""

        enriched_results = []
        for perf_record in volume_performances:
            enriched = self.enrich_volume_performance(perf_record)
            enriched_results.append(enriched)

        logger.info(f"Enriched {len(enriched_results)} volume performance records")
        return enriched_results

    def _get_controller_unit_from_id(self, controller_id: str) -> str:
        """Get controller unit designation (A/B) based on controller ID."""
        logger.debug(f"_get_controller_unit_from_id called with controller_id: '{controller_id}', type: {type(controller_id)}")

        if not controller_id or controller_id == 'unknown':
            logger.debug(f"Controller ID is None or 'unknown', returning 'unknown'")
            return 'unknown'

        # Use the same pattern logic as controller enrichment
        # Controllers ending with '00000001' are A, '00000002' are B
        if controller_id.endswith('00000001'):
            logger.debug(f"Controller ID {controller_id} ends with '00000001', returning 'A'")
            return 'A'
        elif controller_id.endswith('00000002'):
            logger.debug(f"Controller ID {controller_id} ends with '00000002', returning 'B'")
            return 'B'
        else:
            # Fallback to simple pattern
            if controller_id.endswith('1'):
                logger.debug(f"Controller ID {controller_id} ends with '1' (fallback), returning 'A'")
                return 'A'
            elif controller_id.endswith('2'):
                logger.debug(f"Controller ID {controller_id} ends with '2' (fallback), returning 'B'")
                return 'B'
            else:
                logger.debug(f"Controller ID {controller_id} doesn't match any pattern, returning 'unknown'")
                return 'unknown'

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

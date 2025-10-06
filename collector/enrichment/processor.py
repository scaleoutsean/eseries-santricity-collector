"""
Enhanced enrichment processor for E-Series Performance Analyzer.

Extracted from app/main.py to collector/enrichment/processor.py for
independence and better architectural separation.
"""

import logging


class EnrichmentProcessor:
    """Enrich performance data with configuration information."""

    def __init__(self, config_collector=None, from_json=False, sys_info=None, config_data=None):
        self.config_collector = config_collector
        self.cache = config_collector.config_cache if config_collector else None
        self.from_json = from_json
        self.sys_info = sys_info or {}
        self.config_data = config_data  # Pre-collected config data for JSON mode
        self.volumes_cached = False
        self.system_cached = False
        self.logger = logging.getLogger(__name__)

        # Initialize enrichment processors using local imports
        from .volume_enrichment import VolumeEnrichmentProcessor
        from .drive_enrichment import DriveEnrichmentProcessor
        from .controller_enrichment import ControllerEnrichmentProcessor
        from .system_enrichment import SystemEnrichmentProcessor
        from .event_enrichment import EventEnrichment
        from .environmental_enrichment import EnvironmentalPowerEnrichment, EnvironmentalTemperatureEnrichment

        # Initialize system enricher
        self.shared_system_cache = {}
        self.system_enricher = SystemEnrichmentProcessor()
        # Set the shared cache directly on the system enricher
        self.system_enricher.system_config_cache = self.shared_system_cache

        # Pass system enricher to other enrichers so they can share the system cache
        self.volume_enricher = VolumeEnrichmentProcessor(system_enricher=self.system_enricher)
        self.drive_enricher = DriveEnrichmentProcessor(system_enricher=self.system_enricher)
        self.controller_enricher = ControllerEnrichmentProcessor(system_enricher=self.system_enricher)
        # Initialize environmental enrichment processors
        self.environmental_power_enricher = EnvironmentalPowerEnrichment(system_enricher=self.system_enricher)
        self.environmental_temperature_enricher = EnvironmentalTemperatureEnrichment(system_enricher=self.system_enricher)

        # Initialize event enrichment processor with default config
        event_config = {
            'enable_event_deduplication': True,
            'event_dedup_window_minutes': 5,
            'grafana_api_token': None,  # Can be configured later if needed
            'grafana_api_url': None
        }
        self.event_enricher = EventEnrichment(config=event_config, system_enricher=self.system_enricher)

        # Set JSON mode for all enrichers (including their system identification helpers)
        if hasattr(self.controller_enricher, 'set_json_mode'):
            self.controller_enricher.set_json_mode(from_json)
        else:
            self.controller_enricher.from_json = from_json
        if hasattr(self.drive_enricher, 'set_json_mode'):
            self.drive_enricher.set_json_mode(from_json)
        else:
            self.drive_enricher.from_json = from_json
        if hasattr(self.volume_enricher, 'set_json_mode'):
            self.volume_enricher.set_json_mode(from_json)
        else:
            self.volume_enricher.from_json = from_json
        # System enricher should also have JSON mode set
        if hasattr(self.system_enricher, 'set_json_mode'):
            self.system_enricher.set_json_mode(from_json)
        else:
            self.system_enricher.from_json = from_json

        # Environmental and event enrichers access system data through the system_enricher
        self.enrichment_data_loaded = False

    def _load_enrichment_data(self):
        """Load enrichment data from either pre-collected config data or API calls."""
        if self.enrichment_data_loaded:
            return  # Already loaded

        try:
            # If we have pre-collected config data (JSON mode), use it directly
            if self.config_data:
                self.logger.info("Loading enrichment data from pre-collected config data...")
                self._load_from_config_data(self.config_data)
                self.enrichment_data_loaded = True
                self.logger.info("Successfully loaded enrichment data from config data")
                return

            # Fallback to API collection (live mode)
            self.logger.info("Loading enrichment data from API...")

            # No pre-collected config data available - this is an error in current architecture
            self.logger.error("No config_data provided to EnrichmentProcessor - enrichment will be disabled")
            self.enrichment_data_loaded = False
            return

        except Exception as e:
            self.logger.error(f"Failed to load enrichment data: {e}")
            # Continue without enrichment data instead of failing
            self.enrichment_data_loaded = False

    def _load_from_config_data(self, config_data):
        """Load enrichment data from pre-collected configuration data."""
        self.logger.info(f"Loading from pre-collected config data: {list(config_data.keys())}")

        # Extract data from config_data dictionary
        # Each config type is a list of BaseModel objects or dictionaries
        def extract_raw_data(data_list):
            """Extract raw data from a list of BaseModel objects or dictionaries."""
            if not data_list:
                return []

            raw_data = []
            for i, item in enumerate(data_list):
                self.logger.debug(f"extract_raw_data[{i}]: type={type(item)}, has_raw_data={hasattr(item, '_raw_data')}")
                if hasattr(item, '_raw_data'):
                    extracted = item._raw_data
                    has_id = 'id' in extracted
                    keys = list(extracted.keys())[:5]
                    self.logger.debug(f"extract_raw_data[{i}]: _raw_data has id={has_id}, keys={keys}")
                    raw_data.append(extracted)
                elif hasattr(item, '__dict__'):
                    extracted = item.__dict__
                    has_id = 'id' in extracted
                    keys = list(extracted.keys())[:5]
                    self.logger.debug(f"extract_raw_data[{i}]: __dict__ has id={has_id}, keys={keys}")
                    raw_data.append(extracted)
                elif isinstance(item, dict):
                    has_id = 'id' in item
                    keys = list(item.keys())[:5]
                    self.logger.debug(f"extract_raw_data[{i}]: dict has id={has_id}, keys={keys}")
                    raw_data.append(item)
                else:
                    # Fallback - convert to dict
                    self.logger.debug(f"extract_raw_data[{i}]: fallback conversion")
                    raw_data.append(dict(item) if hasattr(item, 'items') else str(item))
            return raw_data

        # Map config data to raw data for each enricher
        # Handle both class names (SystemConfig) and measurement names (config_system)
        hosts_data = extract_raw_data(config_data.get('HostConfig', config_data.get('config_hosts', [])))
        host_groups_data = extract_raw_data(config_data.get('HostGroupsConfig', config_data.get('config_host_groups', [])))
        pools_data = extract_raw_data(config_data.get('StoragePoolConfig', config_data.get('config_storage_pools', [])))
        volumes_data = extract_raw_data(config_data.get('VolumeConfig', config_data.get('config_volumes', [])))
        mappings_data = extract_raw_data(config_data.get('VolumeMappingsConfig', config_data.get('config_volume_mappings', [])))
        cg_members_data = extract_raw_data(config_data.get('VolumeCGMembersConfig', config_data.get('config_volume_cg_members', [])))
        drives_data = extract_raw_data(config_data.get('DriveConfig', config_data.get('config_drives', [])))
        controllers_data = extract_raw_data(config_data.get('ControllerConfig', config_data.get('config_controller', [])))
        system_configs_data = extract_raw_data(config_data.get('SystemConfig', config_data.get('config_system', [])))
        interfaces_data = extract_raw_data(config_data.get('InterfaceConfig', config_data.get('config_interfaces', [])))
        ethernet_data = extract_raw_data(config_data.get('EthernetConfig', config_data.get('config_ethernet_interface', [])))
        tray_data = extract_raw_data(config_data.get('TrayConfig', config_data.get('config_tray', [])))
        interface_config_data = extract_raw_data(config_data.get('InterfaceConfig', config_data.get('config_interfaces', [])))

        self.logger.info(f"Extracted config data: hosts={len(hosts_data)}, volumes={len(volumes_data)}, cg_members={len(cg_members_data)}, drives={len(drives_data)}, controllers={len(controllers_data)}, systems={len(system_configs_data)}")

        # Load into volume enricher
        if volumes_data or pools_data or system_configs_data:
            self.volume_enricher.load_configuration_data(
                hosts_data, host_groups_data, pools_data, volumes_data, mappings_data, system_configs_data, controllers_data
            )
            self.logger.info(f"Volume enricher loaded with {len(volumes_data)} volumes, {len(pools_data)} pools")

        # Load into drive enricher
        if drives_data or pools_data:
            self.drive_enricher.load_configuration_data(drives_data, pools_data, system_configs_data, controllers_data)
            self.logger.info(f"Drive enricher loaded with {len(drives_data)} drives")

        # Load into controller enricher
        if controllers_data:
            self.controller_enricher.load_configuration_data(controllers_data, system_configs_data, interface_config_data)
            self.logger.info(f"Controller enricher loaded with {len(controllers_data)} controllers")

        # Load into system enricher - this is CRITICAL for system metadata
        if system_configs_data:
            self.system_enricher.build_system_config_cache(system_configs_data)
            self.logger.info(f"System enricher loaded with {len(system_configs_data)} system configs")

            # Verify system cache was populated correctly
            if hasattr(self.system_enricher, 'system_config_cache'):
                self.logger.info(f"System config cache populated with {len(self.system_enricher.system_config_cache)} systems")
                for sys_id, sys_info in self.system_enricher.system_config_cache.items():
                    self.logger.debug(f"System cache: {sys_id} -> {sys_info.get('name', 'unknown')} (WWN: {sys_info.get('wwn', 'unknown')})")
        else:
            self.logger.warning("No SystemConfig data found in pre-collected config data")

        # Update cache tracking
        self.volumes_cached = True
        self.system_cached = True
        self.enrichment_data_loaded = True  # CRITICAL: Set the flag to enable enrichment
        self.enrichment_data_loaded = True  # Critical: Mark enrichment data as loaded!

    def _ensure_volumes_cached(self):
        """Ensure volume configuration is cached."""
        if not self.volumes_cached and self.config_collector and self.cache:
            try:
                self.logger.info("Loading volume configuration into cache...")
                from ..schema.models import VolumeConfig
                volumes = self.config_collector.eseries_collector.collect_volumes(VolumeConfig)

                # Cache volumes by ID for fast lookup
                for volume in volumes:
                    cache_key = f"volume:{volume.id}"
                    self.cache.set(cache_key, {
                        'id': volume.id,
                        'label': volume.label,
                        'name': volume.name,
                        'capacity': volume.capacity,
                        'volumeRef': volume.volumeRef,
                        'volumeGroupRef': volume.volumeGroupRef,
                        'wwn': volume.wwn
                    })

                self.cache.set('volumes:count', len(volumes))
                self.volumes_cached = True
                self.logger.info(f"Cached {len(volumes)} volumes for enrichment")

            except Exception as e:
                self.logger.error(f"Failed to cache volumes: {e}")


    def process(self, perf_data, measurement_type=None):
        """Process and enrich performance data with configuration information."""
        # Load enrichment data if available
        self._load_enrichment_data()

        # For controller statistics response format (dict with 'statistics' array or model with _raw_data)
        # Exclude environmental data from controller enrichment
        if ((isinstance(perf_data, dict) and 'statistics' in perf_data) or
            (hasattr(perf_data, '_raw_data') and isinstance(perf_data._raw_data, dict) and 'statistics' in perf_data._raw_data)):

            # Check if this is environmental data by looking for measurement type
            is_environmental = False
            if isinstance(perf_data, dict):
                if perf_data.get('measurement') in ['temp', 'power']:
                    is_environmental = True
                elif 'tags' in perf_data and perf_data.get('tags', {}).get('sensor_type'):
                    is_environmental = True

            if not is_environmental and self.enrichment_data_loaded:
                # If it's a model object, use its _raw_data for the controller enricher
                data_to_enrich = perf_data._raw_data if hasattr(perf_data, '_raw_data') else perf_data
                enriched_data = self.controller_enricher.process(data_to_enrich)
                self.logger.info(f"Processed controller statistics response with {len(enriched_data.get('statistics', []))} records")
                return enriched_data
            elif is_environmental:
                # Process environmental data with dedicated enrichers
                return self._process_environmental_data(perf_data, measurement_type)
            else:
                self.logger.warning("Enrichment data not loaded - returning controller statistics unchanged")
                # Return the raw data if it's a model object
                return perf_data._raw_data if hasattr(perf_data, '_raw_data') else perf_data

        # For performance data lists, determine type and enrich accordingly
        if isinstance(perf_data, list):
            if self.enrichment_data_loaded:

                # Map performance_ measurement types to expected enrichment types
                measurement_type_mapping = {
                    'performance_volume_statistics': 'volume_performance',
                    'performance_drive_statistics': 'drive_performance',
                    'performance_controller_statistics': 'controller_performance',
                    'performance_interface_statistics': 'interface_performance',
                    'performance_system_statistics': 'system_performance'
                }

                # Apply mapping if measurement_type matches performance_ pattern
                if measurement_type and measurement_type in measurement_type_mapping:
                    measurement_type = measurement_type_mapping[measurement_type]
                    self.logger.debug(f"Mapped measurement type to: {measurement_type}")

                # Try to detect measurement type from data structure
                first_record = None
                if not measurement_type and len(perf_data) > 0:
                    first_record = perf_data[0]
                    if 'volumeId' in first_record or 'volume_id' in first_record:
                        measurement_type = 'volume_performance'
                    elif 'diskId' in first_record:
                        measurement_type = 'drive_performance'
                    elif 'interfaceId' in first_record:
                        measurement_type = 'interface_performance'
                    elif 'controllerId' in first_record or 'sourceController' in first_record:
                        measurement_type = 'controller_performance'
                    elif ('storage_system_wwn' in first_record and 'maxCpuUtilization' in first_record) or ('storageSystemWWN' in first_record and 'maxCpuUtilization' in first_record):
                        measurement_type = 'system_performance'

                # Route to appropriate enricher
                if measurement_type == 'volume_performance':
                    enriched_data = self.volume_enricher.enrich_volume_performance_batch(perf_data)
                    self.logger.info(f"Enriched {len(enriched_data)} volume performance records with host/pool tags")
                    return enriched_data
                elif measurement_type == 'drive_performance':
                    enriched_data = self.drive_enricher.enrich_drive_performance_batch(perf_data)
                    self.logger.info(f"Enriched {len(enriched_data)} drive performance records with config data")
                    return enriched_data
                elif measurement_type == 'controller_performance':
                    enriched_data = self.controller_enricher.enrich_controller_performance_batch(perf_data)
                    self.logger.info(f"Enriched {len(enriched_data)} controller performance records with config data")
                    return enriched_data
                elif measurement_type == 'interface_performance':
                    enriched_data = self.controller_enricher.enrich_interface_statistics_batch(perf_data)
                    self.logger.info(f"Enriched {len(enriched_data)} interface performance records with config data")
                    return enriched_data
                elif measurement_type == 'system_performance':
                    enriched_data = self.system_enricher.enrich_system_statistics(perf_data)
                    self.logger.info(f"Enriched {len(enriched_data)} system performance records with config data")
                    return enriched_data
                else:
                    self.logger.warning(f"Unknown measurement type: {measurement_type}")
                    return perf_data
            else:
                self.logger.warning("Enrichment data not loaded - returning data unchanged")
                return perf_data

        # For other data types, ensure cached data is available
        if self.cache:
            self._ensure_volumes_cached()

        return perf_data

    def enrich_config_data(self, config_data_dict, sys_info=None):
        """Enrich configuration data using dedicated config enrichment architecture."""
        if not isinstance(config_data_dict, dict):
            return config_data_dict

        # Load enrichment data if needed
        self._load_enrichment_data()

        # Import the config enrichment factory
        from .config_enrichment import get_config_enricher

        enriched_config = {}

        for config_type, config_items in config_data_dict.items():
            if not isinstance(config_items, list) or not config_items:
                enriched_config[config_type] = config_items
                continue

            # Get the appropriate enricher for this config type
            enricher = get_config_enricher(config_type, self.system_enricher, self.volume_enricher)

            # Use the enricher to process all items of this type
            enriched_items = enricher.enrich_config_data(config_items, config_type, sys_info)

            enriched_config[config_type] = enriched_items

            if enriched_items:
                self.logger.info(f"Enriched {len(enriched_items)} {config_type} items using {enricher.__class__.__name__}")
            else:
                self.logger.warning(f"No enriched items returned for {config_type} (input: {len(config_items)} items)")

        return enriched_config

    def enrich_event_data(self, event_data_list, sys_info=None, endpoint_name='events'):
        """Enrich event data with alerting metadata and system information."""
        if not isinstance(event_data_list, list):
            return event_data_list

        # Load enrichment data if needed
        self._load_enrichment_data()

        # Use the dedicated EventEnrichment class for sophisticated event processing
        if self.event_enricher:
            # Prepare system info for the event enricher
            system_info = sys_info or self.sys_info or {}

            # Use the EventEnrichment class which provides:
            # - Alert severity mapping
            # - Deduplication logic
            # - Grafana annotation support
            # - System metadata enrichment
            enriched_events = self.event_enricher.enrich_event_data(
                endpoint_name=endpoint_name,
                raw_data=event_data_list
            )

            self.logger.info(f"Enriched {len(enriched_events)} event items using EventEnrichment processor")
            return enriched_events

        # Fallback to basic enrichment if EventEnrichment is not available
        self.logger.warning("EventEnrichment processor not available - using basic enrichment")

        enriched_events = []

        for event_item in event_data_list:
            # Start with original item
            enriched_item = event_item.copy() if isinstance(event_item, dict) else event_item

            # Extract raw data if it's a BaseModel object
            if hasattr(event_item, '_raw_data'):
                enriched_item = event_item._raw_data.copy()
            elif hasattr(event_item, '__dict__'):
                enriched_item = event_item.__dict__.copy()

            # Add system information - prioritize cache (real data), fallback to sys_info
            event_system_id = enriched_item.get('system_id')
            system_found = False

            # Only try cache lookup if we have a valid system_id
            if (self.system_enricher and self.system_enricher.system_config_cache and
                event_system_id and event_system_id not in (None, 'unknown', '')):
                system_config = self.system_enricher.system_config_cache.get(event_system_id)
                if system_config and isinstance(system_config, dict):
                    enriched_item['storage_system_name'] = system_config.get('name', system_config.get('id', event_system_id))
                    enriched_item['storage_system_wwn'] = system_config.get('wwn', event_system_id)
                    enriched_item['storage_system_model'] = system_config.get('model', None)
                    system_found = True

            if not system_found and self.system_enricher and self.system_enricher.system_config_cache:
                # Fallback: use first system in cache
                for system_wwn, system_config in self.system_enricher.system_config_cache.items():
                    if isinstance(system_config, dict):
                        enriched_item['storage_system_name'] = system_config.get('name', system_config.get('id', system_wwn))
                        enriched_item['storage_system_wwn'] = system_config.get('wwn', system_wwn)
                        enriched_item['storage_system_model'] = system_config.get('model', None)
                        system_found = True
                        break

            if not system_found and sys_info and isinstance(sys_info, dict):
                # Fallback to sys_info parameter
                enriched_item['storage_system_name'] = sys_info.get('name', sys_info.get('id', None))
                enriched_item['storage_system_wwn'] = sys_info.get('wwn', sys_info.get('world_wide_name', None))
                enriched_item['storage_system_model'] = sys_info.get('model', None)
                system_found = True

            if not system_found:
                # No system info available - use None to clearly indicate missing data
                enriched_item['storage_system_name'] = None
                enriched_item['storage_system_wwn'] = None
                enriched_item['storage_system_model'] = None

            enriched_events.append(enriched_item)

        self.logger.info(f"Enriched {len(enriched_events)} event items with basic system information")
        return enriched_events

    def _process_environmental_data(self, env_data, measurement_type: str | None = None):
        """
        Process environmental data (power, temperature) with dedicated enrichers.

        Args:
            env_data: Environmental data to process
            measurement_type: Type of measurement for logging

        Returns:
            Enriched environmental data with system metadata and cleaned sensor types
        """
        # Prepare system info for enrichment
        system_info = {
            'storage_system_id': self.sys_info.get('wwn'),
            'storage_system_name': self.sys_info.get('name')
        }

        # Determine environmental data type and apply appropriate enricher
        if isinstance(env_data, dict):
            measurement_name = env_data.get('measurement', '')

            if measurement_name == 'power' or measurement_type == 'env_power':
                # Extract data list from InfluxDB-style format or direct list
                data_list = env_data.get('data', [env_data]) if 'data' in env_data else [env_data]
                enriched_data = self.environmental_power_enricher.enrich_power_data(data_list)
                self.logger.info(f"Enriched {len(enriched_data)} environmental power records")
                return enriched_data

            elif measurement_name in ['temp', 'temperature'] or measurement_type == 'env_temperature':
                # Extract data list from InfluxDB-style format or direct list
                data_list = env_data.get('data', [env_data]) if 'data' in env_data else [env_data]
                enriched_data = self.environmental_temperature_enricher.enrich(data_list, system_info)
                self.logger.info(f"Enriched {len(enriched_data)} environmental temperature records")
                return enriched_data

        elif isinstance(env_data, list):
            # Direct list of environmental records
            if measurement_type == 'env_power':
                enriched_data = self.environmental_power_enricher.enrich_power_data(env_data)
                self.logger.info(f"Enriched {len(enriched_data)} environmental power records")
                return enriched_data
            elif measurement_type == 'env_temperature':
                enriched_data = self.environmental_temperature_enricher.enrich(env_data, system_info)
                self.logger.info(f"Enriched {len(enriched_data)} environmental temperature records")
                return enriched_data

        # Fallback: return data unchanged if we can't identify the type
        self.logger.warning(f"Unknown environmental data type - returning unchanged: {type(env_data)}")
        return env_data

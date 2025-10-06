"""
Controller Performance Enrichment

Enriches controller performance metrics with:
- controller_id: Controller identifier (from statistics data)
- active: Controller active status from configuration
- model_name: Controller model from configuration
- status: Controller status from configuration
- cache_memory_size: Controller cache size from configuration
- flash_cache_memory_size: Controller flash cache size from configuration
"""

from typing import Dict
import logging

from .system_cross_reference import SystemCrossReference
from .system_identification_helper import SystemIdentificationHelper

logger = logging.getLogger(__name__)

class ControllerEnrichmentProcessor:
    """Processes controller performance enrichment with configuration data"""

    def __init__(self, system_enricher=None):
        self.controller_lookup = {}     # controller_id -> controller_config
        self.interface_lookup = {}      # interface_ref -> interface enrichment data
        self.system_lookup = {}         # system_id/system_wwn -> system_config
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



    def load_configuration_data(self, controllers_data, system_configs_data=None, interface_configs_data=None):
        """Load controller and interface configuration data for enrichment"""
        self.controller_lookup = {}
        self.interface_lookup = {}
        self.system_lookup = {}

        # Load system configurations into SystemCrossReference
        if system_configs_data:
            # Handle both single system config dict and list of system configs
            if isinstance(system_configs_data, dict):
                system_configs_data = [system_configs_data]
            self.system_cross_ref.load_system_configs(system_configs_data)

        # Load controller configurations into SystemCrossReference
        self.system_cross_ref.load_controller_configs(controllers_data)

        # Load controller configurations
        for controller_config in controllers_data:
            controller_id = controller_config.get('controllerRef') or controller_config.get('id')
            if controller_id:
                self.controller_lookup[controller_id] = controller_config

        # Link controllers to systems using system config's controller list
        if system_configs_data:
            # Handle both single system config dict and list of system configs
            if isinstance(system_configs_data, dict):
                system_configs_data = [system_configs_data]

            for system_config in system_configs_data:
                system_controllers = system_config.get('controllers', [])
                if isinstance(system_controllers, list):
                    for controller_info in system_controllers:
                        controller_id = controller_info.get('controllerId')
                        if controller_id and controller_id in self.controller_lookup:
                            # Link controller to its system
                            self.controller_lookup[controller_id]['_system_config'] = system_config
                            logger.debug(f"Linked controller {controller_id} to system {system_config.get('name', system_config.get('id', 'unknown'))}")

        # Load system configurations into lookup for fallback
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

        # Load interface configurations and build interface lookup
        if interface_configs_data:
            # Handle both single interface config dict and list of interface configs
            if isinstance(interface_configs_data, dict):
                interface_configs_data = [interface_configs_data]

            for interface_config in interface_configs_data:
                interface_id = interface_config.get('id') or interface_config.get('interfaceRef')
                logger.debug(f"Processing interface config: id={interface_config.get('id')}, interfaceRef={interface_config.get('interfaceRef')}, final_id={interface_id}")
                if interface_id:
                    # Get controller information from interface config
                    controller_ref = interface_config.get('controllerRef')
                    controller_config = None
                    if controller_ref and controller_ref in self.controller_lookup:
                        controller_config = self.controller_lookup[controller_ref]

                    # Get controller label if we have controller config
                    controller_label = 'unknown'
                    if controller_config:
                        controller_label = self._get_controller_label(controller_config)

                    # Build interface enrichment data
                    interface_enrichment = {
                        'controller_ref': controller_ref,
                        'controller_id': controller_config.get('id', controller_ref) if controller_config else controller_ref,
                        'controller_label': controller_label,  # Use the correctly calculated A/B label
                        'controller_active': controller_config.get('status', 'unknown') == 'optimal' if controller_config else False,
                        'controller_model': controller_config.get('boardId', 'unknown') if controller_config else 'unknown',
                        'controller_status': controller_config.get('status', 'unknown') if controller_config else 'unknown',
                        'interface_name': interface_config.get('name', interface_config.get('interfaceName', 'unknown')),
                        'interface_type': interface_config.get('ioInterfaceTypeData', {}).get('interfaceType', 'unknown'),
                        'interface_data': interface_config,
                        'system_config': None
                    }

                    # Special handling for interface types
                    if interface_enrichment['interface_type'] == 'unknown':
                        # Check if this is an ethernet interface by interfaceRef pattern or presence of ethernet-specific fields
                        interface_ref = interface_config.get('interfaceRef', '')
                        if interface_ref.startswith('28') or 'macAddr' in interface_config or 'ipv4Address' in interface_config:
                            interface_enrichment['interface_type'] = 'ethernet'
                    elif interface_enrichment['interface_type'] in ['pcie']:
                        # Known interface types that we don't specifically monitor
                        interface_enrichment['interface_type'] = 'other'

                    # Add system config if available
                    if controller_config and '_system_config' in controller_config:
                        interface_enrichment['system_config'] = controller_config['_system_config']
                    elif controller_config:
                        # Try to find system config by looking through system lookup
                        for system_config in self.system_lookup.values():
                            system_controllers = system_config.get('controllers', [])
                            if isinstance(system_controllers, list):
                                for sys_controller_info in system_controllers:
                                    if sys_controller_info.get('controllerId') == controller_ref:
                                        interface_enrichment['system_config'] = system_config
                                        break
                                if interface_enrichment.get('system_config'):
                                    break

                    self.interface_lookup[interface_id] = interface_enrichment
                    logger.debug(f"Added interface {interface_id} to lookup")

        logger.info(f"Loaded controller enrichment data: {len(self.controller_lookup)} controllers, {len(self.system_lookup)} systems, {len(self.interface_lookup)} interfaces")

        # Count how many controllers are linked to systems
        linked_controllers = sum(1 for ctrl in self.controller_lookup.values() if '_system_config' in ctrl)
        logger.info(f"Linked {linked_controllers} controllers to their systems")

    def _get_controller_label(self, controller: Dict) -> str:
        """Get controller label (A/B) for enrichment from API physicalLocation"""
        controller_id = controller.get('id', '')

        logger.debug(f"_get_controller_label: controller_id='{controller_id}', type={type(controller_id)}")

        # First, try to get the label from physicalLocation (API provides A/B directly)
        physical_location = controller.get('physicalLocation', {})
        if isinstance(physical_location, dict):
            api_label = physical_location.get('label')
            if api_label and api_label in ['A', 'B']:
                logger.debug(f"Controller {controller_id} has API label: {api_label}")
                return api_label

        # Fallback to pattern matching for older data or missing physicalLocation
        # Match the pattern from the legacy app/enrichment/config_shared.py logic
        # Controllers ending with '00000001' are A, '00000002' are B
        if controller_id.endswith('00000001'):
            logger.debug(f"Controller {controller_id} mapped to unit A (fallback pattern)")
            return 'A'
        elif controller_id.endswith('00000002'):
            logger.debug(f"Controller {controller_id} mapped to unit B (fallback pattern)")
            return 'B'
        else:
            # Final fallback - could use active status, position, or other logic
            fallback_unit = 'A' if controller.get('active', True) else 'B'
            logger.debug(f"Controller {controller_id} using final fallback unit {fallback_unit} (active: {controller.get('active', True)})")
            return fallback_unit

    def enrich_interface_statistics(self, interface_stats) -> Dict:
        """Enrich interface statistics with controller and interface configuration data"""

        # Get interface ID from statistics
        interface_id = self._safe_get(interface_stats, 'interfaceId')
        logger.debug(f"Enriching interface statistics for interface_id: {interface_id}")
        if not interface_id:
            logger.warning("Interface statistics record missing interfaceId")
            return interface_stats

        # Get interface enrichment data
        interface_enrichment = self.interface_lookup.get(interface_id)
        if not interface_enrichment:
            logger.warning(f"Interface {interface_id} not found in configuration")
            logger.debug(f"Available interface IDs in lookup: {list(self.interface_lookup.keys())}")
            return interface_stats

        # Start with original statistics
        if isinstance(interface_stats, dict):
            enriched = interface_stats.copy()
        elif hasattr(interface_stats, '_raw_data'):
            # For model objects, start with raw data and ensure it's fully serialized
            raw_data = self._safe_serialize_basemodel(interface_stats._raw_data)
            enriched = raw_data if isinstance(raw_data, dict) else {}
        else:
            # Fallback: try to convert model to dict and serialize
            if hasattr(interface_stats, '__dict__'):
                dict_data = self._safe_serialize_basemodel(interface_stats.__dict__)
                enriched = dict_data if isinstance(dict_data, dict) else {}
            else:
                enriched = {}
                for field_name in dir(interface_stats):
                    if not field_name.startswith('_'):
                        value = getattr(interface_stats, field_name, None)
                        if not callable(value):
                            enriched[field_name] = self._safe_serialize_basemodel(value)

        # Ensure enriched is always a dictionary
        if not isinstance(enriched, dict):
            enriched = {}

        # Add controller tags
        enriched['controller_id'] = interface_enrichment['controller_id']
        enriched['controller_label'] = interface_enrichment['controller_label']
        enriched['controller_unit'] = interface_enrichment['controller_label']  # Use controller_label as controller_unit for consistency
        enriched['controller_active'] = interface_enrichment['controller_active']
        enriched['controller_model'] = interface_enrichment['controller_model']

        # DEBUG: Log the controller enrichment details
        logger.debug(f"Interface enrichment - interface_id: {interface_id}")
        logger.debug(f"Interface enrichment - controller_id: {interface_enrichment['controller_id']}")
        logger.debug(f"Interface enrichment - controller_label: {interface_enrichment['controller_label']}")
        logger.debug(f"Interface enrichment - Setting controller_unit to: {interface_enrichment['controller_label']}")

        # Add interface tags
        enriched['interface_type'] = interface_enrichment['interface_type']
        enriched['is_management_interface'] = interface_enrichment.get('is_management', False)

        # Add system tags - preserve existing system info if valid, otherwise identify
        existing_system_name = enriched.get('sys_name') or enriched.get('storage_system_name') or enriched.get('system_name')
        existing_system_wwn = enriched.get('sys_id') or enriched.get('storage_system_wwn') or enriched.get('system_wwn')

        system_config = None
        if existing_system_name and existing_system_name != 'unknown' and existing_system_wwn and existing_system_wwn != 'unknown':
            # Use existing system information (from injection)
            enriched['system_name'] = existing_system_name
            enriched['system_wwn'] = existing_system_wwn
            enriched['system_id'] = existing_system_wwn
            logger.debug(f"Interface enrichment: Preserved existing system info - Name: {existing_system_name}, WWN: {existing_system_wwn}")
        else:
            # Use system identification as fallback
            system_config = self.system_identifier.get_system_config_for_performance_data(interface_stats)
            if system_config:
                enriched['system_name'] = system_config.get('name', 'unknown')
                enriched['system_wwn'] = system_config.get('wwn', 'unknown')
                enriched['system_id'] = system_config.get('wwn')
                logger.debug(f"Interface enrichment: Used system identification - Name: {system_config.get('name')}, WWN: {system_config.get('wwn')}")
            else:
                logger.warning("Interface enrichment: No system config found")

        # Set system model and firmware version based on available system_config
        if system_config:
            enriched['system_model'] = system_config.get('chassisType', 'unknown')
            enriched['system_firmware_version'] = system_config.get('fwVersion', 'unknown')
        else:
            enriched['system_model'] = 'unknown'
            enriched['system_firmware_version'] = 'unknown'

        # Add interface-type specific enrichment
        interface_data = interface_enrichment.get('interface_data', {})
        interface_type = interface_enrichment['interface_type']

        if interface_type == 'ib':
            # InfiniBand specific enrichment
            enriched['link_state'] = interface_data.get('linkState')
            enriched['current_speed'] = interface_data.get('currentSpeed')
            enriched['link_width'] = interface_data.get('currentLinkWidth')
            enriched['port_state'] = interface_data.get('portState')
            enriched['channel'] = interface_data.get('channel')
            enriched['global_identifier'] = interface_data.get('globalIdentifier')
            enriched['mtu'] = interface_data.get('maximumTransmissionUnit')
        elif interface_type == 'iscsi':
            # iSCSI specific enrichment
            enriched['link_status'] = interface_data.get('linkStatus')
            enriched['current_speed'] = interface_data.get('currentSpeed')
            enriched['channel'] = interface_data.get('channel')
            enriched['ipv4_address'] = interface_data.get('ipv4Address')
            enriched['ipv4_enabled'] = interface_data.get('ipv4Enabled')
            enriched['tcp_port'] = interface_data.get('tcpListenPort')
        elif interface_type == 'ethernet':
            # Ethernet specific enrichment (management interfaces)
            enriched['link_status'] = interface_data.get('linkStatus')
            enriched['current_speed'] = interface_data.get('currentSpeed')
            enriched['interface_name'] = interface_data.get('interfaceName')
            enriched['mac_address'] = interface_data.get('macAddr')
            enriched['ipv4_address'] = interface_data.get('ipv4Address')
            enriched['full_duplex'] = interface_data.get('fullDuplex')

        return enriched

    def enrich_interface_statistics_batch(self, interface_statistics):
        """Enrich a batch of interface statistics"""

        enriched_results = []
        for stats_record in interface_statistics:
            enriched = self.enrich_interface_statistics(stats_record)
            enriched_results.append(enriched)

        logger.info(f"Enriched {len(enriched_results)} interface statistics records")
        return enriched_results

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

    def enrich_controller_performance(self, controller_performance) -> Dict:
        """Enrich a single controller performance measurement with configuration data"""

        # Debug logging to understand the data structure
        logger.debug(f"Controller performance object type: {type(controller_performance)}")
        if hasattr(controller_performance, '__dict__'):
            logger.debug(f"Controller performance attributes: {list(controller_performance.__dict__.keys())}")
        if isinstance(controller_performance, dict):
            logger.debug(f"Controller performance keys: {list(controller_performance.keys())}")

        # Get controller ID from statistics (try both fields)
        # First try direct access (for individual records)
        controller_id = self._safe_get(controller_performance, 'controllerId') or self._safe_get(controller_performance, 'sourceController')

        # If not found, check if this is a wrapper with statistics array
        if not controller_id and isinstance(controller_performance, dict) and 'statistics' in controller_performance:
            stats_array = controller_performance.get('statistics', [])
            if stats_array and len(stats_array) > 0:
                # Extract controller ID from first statistics record
                first_stat = stats_array[0]
                controller_id = self._safe_get(first_stat, 'controllerId') or self._safe_get(first_stat, 'sourceController')
                logger.debug(f"Extracted controller_id from statistics array: {controller_id}")

        logger.debug(f"Final extracted controller_id: {controller_id}")
        if not controller_id:
            logger.warning("Controller performance record missing controllerId/sourceController")
            return controller_performance

        # Get controller configuration
        controller_config = self.controller_lookup.get(controller_id)
        if not controller_config:
            logger.warning(f"Controller {controller_id} not found in configuration")
            return controller_performance

        # Start with original performance data
        if isinstance(controller_performance, dict):
            enriched = controller_performance.copy()
        elif hasattr(controller_performance, '_raw_data'):
            # For model objects, start with raw data and ensure it's fully serialized
            raw_data = self._safe_serialize_basemodel(controller_performance._raw_data)
            enriched = raw_data if isinstance(raw_data, dict) else {}
        else:
            # Fallback: try to convert model to dict and serialize
            if hasattr(controller_performance, '__dict__'):
                dict_data = self._safe_serialize_basemodel(controller_performance.__dict__)
                enriched = dict_data if isinstance(dict_data, dict) else {}
            else:
                enriched = {}
                for field_name in dir(controller_performance):
                    if not field_name.startswith('_'):
                        value = getattr(controller_performance, field_name, None)
                        if not callable(value):
                            enriched[field_name] = self._safe_serialize_basemodel(value)

        # Ensure enriched is always a dictionary
        if not isinstance(enriched, dict):
            enriched = {}

        # Add tags
        enriched['controller_id'] = controller_id
        enriched['active'] = controller_config.get('active', False)
        enriched['model_name'] = controller_config.get('modelName', 'unknown')
        enriched['status'] = controller_config.get('status', 'unknown')

        # Add controller_unit tag (A/B designation)
        enriched['controller_unit'] = self._get_controller_label(controller_config)

        # Add system tags using unified system identification
        system_config = self.system_identifier.get_system_config_for_performance_data(controller_performance)
        if system_config:
            enriched['storage_system_name'] = system_config.get('name', 'unknown')
            enriched['storage_system_wwn'] = system_config.get('wwn', 'unknown')
            enriched['system_id'] = system_config.get('wwn')
        else:
            logger.warning("No system config found for controller performance data")

        # Extract additional system info from system_config if available
        if system_config:
            enriched['system_model'] = system_config.get('chassisType', 'unknown')
            enriched['system_firmware_version'] = system_config.get('fwVersion', 'unknown')
        else:
            enriched['system_model'] = 'unknown'
            enriched['system_firmware_version'] = 'unknown'

        # Add fields (additional data points)
        enriched['cache_memory_size'] = controller_config.get('cacheMemorySize', 0)
        enriched['flash_cache_memory_size'] = controller_config.get('flashCacheMemorySize', 0)

        # Optional: Add other useful controller config data as fields
        enriched['manufacturer'] = controller_config.get('manufacturer', 'unknown')
        enriched['serial_number'] = controller_config.get('serialNumber', 'unknown')
        enriched['part_number'] = controller_config.get('partNumber', 'unknown')

        return enriched

    def enrich_controller_performance_batch(self, controller_performances):
        """Enrich a batch of controller performance measurements"""

        enriched_results = []
        for perf_record in controller_performances:
            enriched = self.enrich_controller_performance(perf_record)
            enriched_results.append(enriched)

        logger.info(f"Enriched {len(enriched_results)} controller performance records")
        return enriched_results

    def process(self, controller_stats_response: Dict) -> Dict:
        """
        Process and enrich controller statistics response with special handling for list format

        Handles cases where API returns:
        - [] (empty list) - returns empty statistics
        - 1-2 items - processes all items
        - >2 items - sorts by observedTimeInMS descending and takes 2 most recent

        Format: {'statistics': [...], 'tokenId': '...'}
        """

        if not isinstance(controller_stats_response, dict) or 'statistics' not in controller_stats_response:
            logger.warning("Invalid controller statistics response format")
            return controller_stats_response

        statistics = controller_stats_response.get('statistics', [])

        # Handle empty list case
        if not statistics:
            logger.info("Controller statistics response contains no data")
            enriched_response = controller_stats_response.copy()
            enriched_response['statistics'] = []
            return enriched_response

        # Handle case with more than 2 items - sort by observedTimeInMS descending and take 2 most recent
        if len(statistics) > 2:
            logger.info(f"Controller statistics has {len(statistics)} items, sorting by observedTimeInMS and taking 2 most recent")
            # Sort by observedTimeInMS in descending order (most recent first)
            try:
                statistics_sorted = sorted(
                    statistics,
                    key=lambda x: int(x.get('observedTimeInMS', 0)),
                    reverse=True
                )
                statistics = statistics_sorted[:2]  # Take 2 most recent
                logger.info(f"Selected {len(statistics)} most recent controller statistics")
            except (ValueError, TypeError) as e:
                logger.warning(f"Error sorting controller statistics by observedTimeInMS: {e}")
                # If sorting fails, just take first 2 items
                statistics = statistics[:2]

        # Enrich the statistics array
        enriched_statistics = self.enrich_controller_performance_batch(statistics)

        # Return enriched response
        enriched_response = controller_stats_response.copy()
        enriched_response['statistics'] = enriched_statistics

        logger.info(f"Processed controller statistics response with {len(enriched_statistics)} controller records")
        return enriched_response

    def enrich_controller_statistics_response(self, controller_stats_response: Dict) -> Dict:
        """
        Legacy method - use process() instead
        Enrich the entire controller statistics response (which contains a statistics array)
        This handles the specific format: {'statistics': [...], 'tokenId': '...'}
        """
        return self.process(controller_stats_response)

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

"""
Base Configuration Data Enrichment for E-Series Performance Analyzer

This module provides the base framework for enriching configuration data
with system-level context and standardized tagging for InfluxDB storage.

All config enrichers inherit from BaseConfigEnricher to ensure consistent
system-level enrichment across different configuration types.
"""

import logging
from typing import Dict, List, Any, Optional, Union
from .system_identification_helper import SystemIdentificationHelper
from abc import ABC, abstractmethod

LOG = logging.getLogger(__name__)

class BaseConfigEnricher(ABC):
    """
    Base class for all configuration data enrichers.

    Provides common system-level enrichment that all config types need:
    - storage_system_name tags (name, wwn, model)
    - timestamp normalization
    - ID field standardization
    - Common field validation
    """

    def __init__(self, system_enricher=None):
        """
        Initialize base config enricher.

        Args:
            system_enricher: System enricher instance for system info lookup
        """
        self.system_enricher = system_enricher
        self.system_identifier = SystemIdentificationHelper(system_enricher)
        self._system_cache = {}

    def enrich_config_data(self, config_data: Union[List[Dict], Dict],
                          config_type: str, sys_info: Optional[Dict] = None) -> List[Dict]:
        """
        Main enrichment entry point. Applies both base and type-specific enrichment.

        Args:
            config_data: Raw config data (list of dicts or single dict)
            config_type: Configuration type (e.g., 'drive_config', 'volume_config')
            sys_info: Optional system info fallback

        Returns:
            List of enriched configuration dictionaries
        """
        if not config_data:
            return []

        # Normalize to list
        if isinstance(config_data, dict):
            config_data = [config_data]
        elif not isinstance(config_data, list):
            LOG.warning(f"Unexpected config data type for {config_type}: {type(config_data)}")
            return []

        enriched_items = []

        for config_item in config_data:
            # Extract raw data if it's a BaseModel object
            raw_item = self._extract_raw_data(config_item)

            # Apply base system enrichment
            enriched_item = self._add_system_tags(raw_item, sys_info)

            # Validate system enrichment worked properly - fail fast if not
            if not enriched_item.get('storage_system_name'):
                LOG.error(f"Config enrichment failed - no system info available for {config_type} item: {raw_item.get('id', 'no_id')}")
                raise ValueError(f"Config enrichment requires valid system information for {config_type} items")

            # Apply type-specific enrichment (implemented by subclasses)
            enriched_item = self.enrich_item(enriched_item, config_type)

            # Validate and clean up
            enriched_item = self._validate_and_cleanup(enriched_item, config_type)

            if enriched_item:  # Only add valid items
                enriched_items.append(enriched_item)

        LOG.debug(f"Enriched {len(enriched_items)} {config_type} items")
        return enriched_items

    def _extract_raw_data(self, config_item: Any) -> Dict[str, Any]:
        """Extract raw dictionary data from various input formats."""
        if isinstance(config_item, dict):
            return config_item.copy()
        elif hasattr(config_item, '_raw_data'):
            return config_item._raw_data.copy()
        elif hasattr(config_item, '__dict__'):
            return config_item.__dict__.copy()
        else:
            LOG.warning(f"Cannot extract data from config item type: {type(config_item)}")
            return {}

    def _add_system_tags(self, raw_item: Dict[str, Any], sys_info: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Add system-level tags that every config item needs.

        Priority: system_enricher cache > sys_info parameter > defaults
        """
        enriched_item = raw_item.copy()

        # Get system configuration using proper identification
        system_config = self.system_identifier.get_system_config_for_performance_data(raw_item)
        if system_config:
            enriched_item['storage_system_name'] = system_config.get('name')
            enriched_item['storage_system_wwn'] = system_config.get('wwn')
            enriched_item['storage_system_model'] = system_config.get('model')
            return enriched_item

        # No system config found - this indicates a serious problem
        LOG.error("No system config available for config enrichment - this indicates initialization failure")
        return None  # Signal failure

    def _get_system_from_cache(self, system_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get system info from enricher cache."""
        if not self.system_enricher or not hasattr(self.system_enricher, 'system_config_cache'):
            return None

        cache = self.system_enricher.system_config_cache
        if not cache:
            return None

        # If system_id is provided, try to find the specific system
        if system_id:
            system_config = cache.get(system_id)
            if system_config:
                return system_config

        # Fallback: Return the first (and typically only) system in cache
        for system_key, system_config in cache.items():
            if isinstance(system_config, dict):
                return system_config

        return None

    def _validate_and_cleanup(self, enriched_item: Dict[str, Any], config_type: str) -> Optional[Dict[str, Any]]:
        """
        Validate and clean up enriched item before returning.

        - Ensure required fields exist
        - Remove None/empty values that shouldn't be stored
        - Standardize field types
        """
        if not enriched_item or not isinstance(enriched_item, dict):
            return None

        # Ensure we have an ID field (critical for InfluxDB)
        if not enriched_item.get('id'):
            # Try common ID field variations
            id_candidates = ['ref', 'volumeRef', 'driveRef', 'controllerRef', 'hostRef', 'trayRef', 'trayId']
            for candidate in id_candidates:
                if enriched_item.get(candidate):
                    enriched_item['id'] = enriched_item[candidate]
                    break
            else:
                # For tray configs, create a composite ID from partNumber and serialNumber
                if config_type == 'TrayConfig' and enriched_item.get('partNumber') and enriched_item.get('serialNumber'):
                    enriched_item['id'] = f"{enriched_item['partNumber']}_{enriched_item['serialNumber']}"
                else:
                    # Still no ID - this might be problematic
                    LOG.warning(f"No ID field found for {config_type} item")
                    enriched_item['id'] = 'unknown'

        # Remove private fields and None values
        cleaned_item = {}
        for key, value in enriched_item.items():
            if key.startswith('_'):
                continue  # Skip private fields
            if value is not None:
                cleaned_item[key] = value

        return cleaned_item if cleaned_item else None

    @abstractmethod
    def enrich_item(self, raw_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Apply type-specific enrichment to a config item.

        This method must be implemented by subclasses to provide
        config-type-specific enrichment logic.

        Args:
            raw_item: Raw config item with system tags already added
            config_type: Type of configuration being enriched

        Returns:
            Enriched config item with type-specific fields added
        """
        pass


class DefaultConfigEnricher(BaseConfigEnricher):
    """
    Default enricher for config types that don't have dedicated enrichers.

    Provides basic enrichment suitable for simple config types.
    """

    def enrich_item(self, raw_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Apply basic enrichment for simple config types.

        - Add name/label standardization
        - Preserve all original fields (don't discard valuable data)
        - Basic field promotion to tags
        """
        enriched_item = raw_item.copy()

        # Debug logging for tray configs
        if config_type == 'TrayConfig':
            LOG.debug(f"DefaultConfigEnricher.enrich_item - TrayConfig raw_item keys: {list(raw_item.keys())}")
            LOG.debug(f"DefaultConfigEnricher.enrich_item - TrayConfig raw_item: {raw_item}")

        # Standardize name field (common pattern across many config types)
        name_value = enriched_item.get('label') or enriched_item.get('name') or 'unknown'
        enriched_item[f'{config_type}_name'] = name_value

        # Special handling for TrayConfig: trim trailing spaces from partNumber and serialNumber
        if config_type == 'TrayConfig':
            if enriched_item.get('partNumber') and isinstance(enriched_item['partNumber'], str):
                enriched_item['partNumber'] = enriched_item['partNumber'].rstrip()
            if enriched_item.get('serialNumber') and isinstance(enriched_item['serialNumber'], str):
                enriched_item['serialNumber'] = enriched_item['serialNumber'].rstrip()

        # Keep all original fields - don't discard valuable data like partNumber, serialNumber, etc.
        # The _validate_and_cleanup method will handle ID field generation and cleanup

        if config_type == 'TrayConfig':
            LOG.debug(f"DefaultConfigEnricher.enrich_item - TrayConfig enriched_item keys: {list(enriched_item.keys())}")
            LOG.debug(f"DefaultConfigEnricher.enrich_item - TrayConfig enriched_item: {enriched_item}")

        return enriched_item


def get_config_enricher(config_type: str, system_enricher=None, volume_enricher=None) -> BaseConfigEnricher:
    """
    Factory function to get the appropriate enricher for a config type.

    Args:
        config_type: Type of configuration (e.g., 'drive_config', 'volume_config')
        system_enricher: System enricher instance

    Returns:
        Appropriate config enricher instance
    """
    # Import specific enrichers here to avoid circular imports
    from .config_drive_enrichment import DriveConfigEnricher
    from .config_controller_enrichment import ControllerConfigEnricher
    from .config_storage_enrichment import StorageConfigEnricher
    from .config_shared import SharedConfigEnricher

    # Map CONFIGURATION measurement names to their dedicated enrichers
    # Note: These are for enriching config data itself, not performance data
    enricher_map = {
        # Drive configuration enrichment (from actual file names: configuration_drive_config_*)
        'configuration_drive_config': DriveConfigEnricher,
        'config_driveconfig': DriveConfigEnricher,  # From schema validator
        'driveconfig': DriveConfigEnricher,
        'drive_config': DriveConfigEnricher,

        # Controller configuration enrichment (from actual file names: configuration_controller_config_*)
        'configuration_controller_config': ControllerConfigEnricher,
        'config_controllerconfig': ControllerConfigEnricher,  # From schema validator
        'controllerconfig': ControllerConfigEnricher,
        'controller_config': ControllerConfigEnricher,

        # Storage pool configuration enrichment (from schema: config_storagepoolconfig, config_storage)
        'configuration_storage_pool': StorageConfigEnricher,
        'configuration_storage': StorageConfigEnricher,
        'config_storagepoolconfig': StorageConfigEnricher,  # From schema validator
        'config_storage': StorageConfigEnricher,  # From schema validator
        'storagepoolconfig': StorageConfigEnricher,
        'storage': StorageConfigEnricher,
    }

    # Check for dedicated enricher
    enricher_class = enricher_map.get(config_type)
    if enricher_class:
        return enricher_class(system_enricher)

    # Check if it should use shared enricher (for configuration measurements)
    shared_types = {
        # Volume configuration measurements (from file names and schema validator)
        'configuration_volume', 'configuration_volumes', 'configuration_volume_mappings',
        'config_volumeconfig', 'config_volume', 'config_volumes', 'config_volumemappingsconfig',
        'volume', 'volumes', 'volumeconfig', 'volumemappingsconfig',
        'VolumeConfig', 'VolumeMappingsConfig',  # PascalCase versions from collector

        # Network/Ethernet configuration measurements (from file names and schema validator)
        'configuration_ethernet', 'configuration_interfaces',
        'config_ethernet', 'config_interfaceconfig',
        'ethernet', 'interfaces', 'interfaceconfig',
        'InterfaceConfig',  # PascalCase version from collector

        # Host configuration measurements (from file names and schema validator)
        'configuration_host', 'configuration_hosts', 'configuration_host_groups',
        'config_hosts', 'config_host_groups',
        'host', 'hosts', 'hostconfig', 'host_groups',
        'HostConfig', 'HostGroupsConfig',  # PascalCase versions from collector

        # Other simple configuration measurements (from file names and schema validator)
        'configuration_snapshot', 'configuration_async', 'configuration_hardware',
        'configuration_system', 'configuration_tray', 'configuration_controller', 'configuration_drives',
        'config_snapshot', 'config_systemconfig', 'config_trayconfig', 'config_controller', 'config_drives',
        'snapshot', 'async', 'hardware', 'system', 'tray', 'controller', 'drives',
        'SystemConfig', 'TrayConfig', 'StoragePoolConfig', 'ControllerConfig', 'DriveConfig'  # PascalCase versions from collector
    }

    if config_type in shared_types or any(t in config_type for t in shared_types):
        return SharedConfigEnricher(system_enricher, volume_enricher)

    # Fallback to default enricher
    LOG.debug(f"Using default enricher for config type: {config_type}")
    return DefaultConfigEnricher(system_enricher)
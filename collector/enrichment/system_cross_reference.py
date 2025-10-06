"""
Cross-referencing utilities for system lookup across enrichers

Provides centralized system lookup logic with consistent fallback hierarchy:
1. system_id already tagged to performance data (from ingestion)
2. Controller lookup using controller ID from performance data
3. Fallback to config sources (pool, drive, etc.)
"""

from typing import Dict, List, Optional, Any, Union
import logging

logger = logging.getLogger(__name__)

class SystemCrossReference:
    """
    Simple system lookup utility for enrichers.

    Just looks up system config by system_id - no magic, no fallbacks.
    """

    def __init__(self):
        self.system_lookup = {}         # system_id -> system_config
        self.controller_lookup = {}     # controller_id -> controller_config

    def load_system_configs(self, system_configs: List[Dict[str, Any]]) -> None:
        """Load system configurations into lookup table."""
        self.system_lookup.clear()

        for system_config in system_configs:
            system_wwn = system_config.get('wwn')
            if system_wwn:
                # Use WWN as the key since that's our system_id
                self.system_lookup[system_wwn] = system_config

        logger.debug(f"Loaded {len(self.system_lookup)} system configurations")

    def load_controller_configs(self, controllers_data: List[Dict[str, Any]]) -> None:
        """Load controller configurations into lookup table."""
        self.controller_lookup.clear()

        for controller_config in controllers_data:
            controller_id = controller_config.get('controllerRef') or controller_config.get('id')
            if controller_id:
                self.controller_lookup[controller_id] = controller_config

        logger.debug(f"Loaded {len(self.controller_lookup)} controller configurations")

    def find_system_for_performance_data(self,
                                       performance_data: Union[Dict, Any],
                                       **kwargs) -> Optional[Dict[str, Any]]:
        """
        Find system configuration for performance data.

        Simplified: Just look up the system_id that was injected during collection.
        No fallbacks, no magic - if system_id is missing, something went wrong.
        """
        # Helper to safely get values from performance data
        def safe_get(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            elif hasattr(obj, key):
                return getattr(obj, key, default)
            elif hasattr(obj, '_raw_data') and isinstance(obj._raw_data, dict):
                return obj._raw_data.get(key, default)
            return default

        # Get system_id that should have been injected during collection
        system_id = safe_get(performance_data, 'system_id')

        if not system_id:
            logger.error("No system_id found in performance data - data collection failed")
            return None

        # Look up in system cache
        system_config = self.system_lookup.get(system_id)
        if system_config:
            logger.debug(f"Found system '{system_config.get('name')}' for system_id: {system_id}")
            return system_config
        else:
            logger.error(f"System {system_id} not found in system lookup cache")
            return None

    def get_system_tags(self, system_config: Dict[str, Any]) -> Dict[str, str]:
        """Extract standard system tags from system configuration with validation.

        Critical system attributes (name, wwn) must be present and valid.
        We use WWN as the system_id since that's the unique identifier throughout the application.
        """
        # Extract values with defaults for non-critical fields
        system_name = system_config.get('name', 'unknown')
        system_wwn = system_config.get('wwn', 'unknown')
        system_id = system_wwn  # Use WWN as system_id, not the JSON 'id' field which is just sequential
        system_model = system_config.get('model', 'unknown')
        system_firmware_version = system_config.get('fwVersion', 'unknown')  # Note: it's 'fwVersion' not 'firmwareVersion'

        # Debug logging to see what system config contains
        logger.debug(f"get_system_tags called with system_config keys: {list(system_config.keys())}")
        logger.debug(f"Extracted system_name='{system_name}', system_wwn='{system_wwn}'")

        # Validate critical system attributes - these should never be 'unknown' given our validation
        if system_name == 'unknown':
            logger.error(f"Critical system attribute 'name' is missing from system config: {system_config}")
            raise ValueError(f"Critical system attribute 'name' is missing or unknown for system config")
        if system_wwn == 'unknown':
            logger.error(f"Critical system attribute 'wwn' is missing from system config: {system_config}")
            raise ValueError(f"Critical system attribute 'wwn' is missing or unknown for system config")

        return {
            'storage_system_name': system_name,
            'system_id': system_id,
            'system_model': system_model,
            'system_firmware_version': system_firmware_version,
        }

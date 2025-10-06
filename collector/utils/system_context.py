"""Unified system context manager for E-Series Performance Analyzer.

Provides a single source of truth for system identification across all data types
and collection modes (Live API vs JSON Replay).
"""

import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SystemContext:
    """System context information."""
    wwn: str
    name: str
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    management_ips: Optional[list] = None
    source: str = "unknown"


class UnifiedSystemContextManager:
    """
    Centralized system context manager that provides consistent system information
    across all data extraction operations.

    This eliminates the need for multiple system identification approaches and
    ensures all records have consistent system tagging.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._system_cache: Dict[str, SystemContext] = {}
        self._primary_system_wwn: Optional[str] = None

    def register_system_from_live_api(self, system_config: Dict[str, Any]) -> str:
        """Register system context from Live API system config response.

        Args:
            system_config: System configuration from API call

        Returns:
            System WWN
        """
        wwn = system_config.get('wwn', '').upper()
        if not wwn:
            raise ValueError("System config missing WWN field")

        if not system_config.get('name'):
            raise ValueError(f"System config missing name field for WWN {wwn}")

        context = SystemContext(
            wwn=wwn,
            name=system_config.get('name'),
            model=system_config.get('chassisType', system_config.get('model')),
            firmware_version=system_config.get('fwVersion'),
            management_ips=system_config.get('managementPaths', []),
            source="live_api"
        )

        self._system_cache[wwn] = context
        self._primary_system_wwn = wwn

        self.logger.info(f"Registered system from Live API - WWN: {wwn}, Name: {context.name}")
        return wwn

    def register_system_from_json_replay(self, system_wwn: str, system_config: Optional[Dict[str, Any]] = None) -> str:
        """Register system context from JSON replay mode.

        Args:
            system_wwn: System WWN from SYSTEM_ID environment variable
            system_config: Optional system configuration from JSON file

        Returns:
            System WWN
        """
        wwn = system_wwn.upper()

        if system_config:
            # Extract from system config JSON (handles both old and new formats)
            from .data_extraction import extract_system_name_from_config
            config_name = extract_system_name_from_config(system_config)

            if config_name:
                # Successfully extracted real name from config
                context = SystemContext(
                    wwn=wwn,
                    name=config_name,
                    model=self._extract_config_field(system_config, 'chassisType', 'model'),
                    firmware_version=self._extract_config_field(system_config, 'fwVersion'),
                    management_ips=self._extract_config_field(system_config, 'managementPaths', default=[]),
                    source="json_replay_with_config"
                )
            else:
                # Config exists but no name found - this is an error condition
                self.logger.error(f"System config exists but no name could be extracted for WWN {wwn}")
                raise ValueError(f"System config provided but no system name found for WWN {wwn}")
        else:
            # No config provided - this is also an error condition in JSON replay mode
            self.logger.error(f"JSON replay mode requires system config for WWN {wwn}")
            raise ValueError(f"JSON replay mode requires system configuration for WWN {wwn}")

        self._system_cache[wwn] = context
        self._primary_system_wwn = wwn

        self.logger.info(f"Registered system from JSON replay - WWN: {wwn}, Name: {context.name}, Source: {context.source}")
        return wwn

    def get_system_context(self, wwn: Optional[str] = None) -> Optional[SystemContext]:
        """Get system context by WWN or primary system.

        Args:
            wwn: System WWN (if None, returns primary system)

        Returns:
            SystemContext or None if not found
        """
        if wwn:
            return self._system_cache.get(wwn.upper())
        elif self._primary_system_wwn:
            return self._system_cache.get(self._primary_system_wwn)
        else:
            return None

    def get_system_tags(self, wwn: Optional[str] = None) -> Dict[str, str]:
        """Get system tags for record injection.

        Args:
            wwn: System WWN (if None, uses primary system)

        Returns:
            Dictionary of system tags ready for injection into records

        Raises:
            RuntimeError: If no system context is found (indicates registration failure)
        """
        context = self.get_system_context(wwn)
        if not context:
            raise RuntimeError(f"No system context found for WWN: {wwn}. System registration may have failed.")

        return {
            'system_id': context.wwn,
            'system_wwn': context.wwn,
            'sys_id': context.wwn,
            'sys_name': context.name,
            'storage_system_wwn': context.wwn,
            'storage_system_name': context.name,
            'system_name': context.name
        }

    def inject_system_context(self, records: list, wwn: Optional[str] = None) -> None:
        """Inject system context into a list of records.

        Args:
            records: List of dictionaries to inject system context into
            wwn: System WWN (if None, uses primary system)
        """
        if not records:
            return

        system_tags = self.get_system_tags(wwn)

        for record in records:
            if isinstance(record, dict):
                # Only inject if not already present (preserve existing values)
                for tag_key, tag_value in system_tags.items():
                    if tag_key not in record or record[tag_key] in ('unknown', '', None):
                        record[tag_key] = tag_value

        context = self.get_system_context(wwn)
        context_name = context.name if context else 'unknown'
        self.logger.debug(f"Injected system context ({context_name}) into {len(records)} records")

    def _extract_config_field(self, config_data: Any, *field_names, default=None):
        """Extract field from config data handling both old and new formats."""
        if not config_data:
            return default

        # Handle wrapped format
        if isinstance(config_data, dict) and 'data' in config_data:
            actual_config = config_data['data']
        else:
            actual_config = config_data

        # Handle list format
        if isinstance(actual_config, list) and len(actual_config) > 0:
            actual_config = actual_config[0]

        # Extract field
        if isinstance(actual_config, dict):
            for field_name in field_names:
                if field_name in actual_config:
                    return actual_config[field_name]

        return default


# Global instance
system_context_manager = UnifiedSystemContextManager()
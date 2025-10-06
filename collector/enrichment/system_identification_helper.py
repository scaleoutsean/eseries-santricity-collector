#!/usr/bin/env python3
"""
System identification helper for E-Series Performance Analyzer

Simple helper for looking up system configuration from performance data.
"""

import logging
from typing import Dict, Any, Optional

LOG = logging.getLogger(__name__)

class SystemIdentificationHelper:
    """
    Simple helper for system identification in performance enrichers.

    With proper initialization and JSON normalization, this is now straightforward:
    1. Look up system by system_id (standard field)
    2. Return system config or None
    """

    def __init__(self, system_enricher=None):
        """Initialize with reference to system enricher cache."""
        self.system_enricher = system_enricher

    def get_system_config_for_performance_data(self, performance_data) -> Optional[Dict[str, Any]]:
        """
        Get system configuration for performance data.

        Args:
            performance_data: Performance data with system_id field

        Returns:
            System config dict if found, None otherwise
        """
        if not self.system_enricher or not hasattr(self.system_enricher, 'system_config_cache'):
            LOG.debug("No system enricher cache available")
            return None

        cache = self.system_enricher.system_config_cache
        if not cache:
            LOG.debug("System enricher cache is empty")
            return None

        # Get system_id from performance data (standard field)
        system_id = self._safe_get(performance_data, 'system_id')
        if not system_id:
            LOG.debug(f"No system_id found in performance data. Available keys: {list(performance_data.keys()) if isinstance(performance_data, dict) else 'not a dict'}")
            return None

        # Debug: Show what we're looking for and what's available
        LOG.debug(f"Looking for system_id='{system_id}' in cache with keys: {list(cache.keys())}")

        # Look up in cache
        system_config = cache.get(system_id)
        if system_config:
            LOG.debug(f"Found system config for {system_id}: {system_config.get('name', 'unnamed')}")
            return system_config
        else:
            LOG.debug(f"No system config found for system_id: {system_id}")
            return None

    def get_system_name(self, performance_data) -> Optional[str]:
        """
        Get just the system name for performance data.

        Args:
            performance_data: Performance data with system_id field

        Returns:
            System name if found, None otherwise
        """
        system_config = self.get_system_config_for_performance_data(performance_data)
        if system_config:
            return system_config.get('name')
        return None

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
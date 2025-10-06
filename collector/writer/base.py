"""
Base writer interface for E-Series Performance Analyzer.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any

# Initialize logger
LOG = logging.getLogger(__name__)

class Writer(ABC):
    """
    Base class for all writers.
    Provides centralized measurement name mapping to avoid duplication across writers.
    """

    # Import centralized mapping from endpoint_categories
    from collector.config.endpoint_categories import ENDPOINT_TO_MEASUREMENT_MAPPING, get_measurement_name

    # Legacy MEASUREMENT_NAME_MAPPING for backwards compatibility
    # This now uses the centralized mapping as the source of truth
    MEASUREMENT_NAME_MAPPING = ENDPOINT_TO_MEASUREMENT_MAPPING.copy()

    # Add legacy wrapper mappings that aren't direct API endpoints
    MEASUREMENT_NAME_MAPPING.update({
        'performance_data': 'performance_volume_statistics',  # performance_data wrapper -> volume
    })

    @classmethod
    def get_final_measurement_name(cls, internal_name: str) -> str:
        """
        Get the final measurement name for storage from an internal measurement name.

        Args:
            internal_name: Internal measurement name used in collector processing

        Returns:
            Final measurement name to be used in storage systems
        """
        return cls.MEASUREMENT_NAME_MAPPING.get(internal_name, internal_name)

    @abstractmethod
    def write(self, data: Dict[str, Any], loop_iteration: int = 1) -> bool:
        """
        Write data to the destination.

        Args:
            data: Dictionary containing data to write
            loop_iteration: Current iteration number for debug file naming

        Returns:
            True if write was successful, False otherwise
        """
        pass

    def close(self, timeout_seconds: int = 90, force_exit_on_timeout: bool = False) -> None:
        """
        Optional method to close the writer and clean up resources.
        Default implementation does nothing - override in subclasses that need cleanup.

        Args:
            timeout_seconds: Timeout for cleanup operations
            force_exit_on_timeout: Whether to force exit on timeout
        """
        pass
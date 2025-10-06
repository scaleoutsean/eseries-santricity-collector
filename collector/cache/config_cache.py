from typing import Dict, List, Optional
import logging

from .cache_manager import CacheManager
from ..config.collection_schedules import ScheduleFrequency, FREQUENCY_MULTIPLIERS
from ..schema.models import (
    DriveConfig,
    VolumeConfig,
    StoragePoolConfig,
    SystemConfig,
    # Import other models as needed
)

class ConfigCache:
    """
    Cache for configuration objects

    Provides:
    - Type-specific retrieval methods
    - Collection scheduling aligned with ScheduleFrequency
    - Cross-object relationships

    Cache TTL is automatically calculated to be longer than the longest collection
    interval to prevent cache misses when collection scheduler attempts to collect.
    """

    @staticmethod
    def calculate_cache_ttl(base_interval: int) -> int:
        """
        Calculate appropriate cache TTL based on collection schedules

        Args:
            base_interval: Base collection interval in seconds

        Returns:
            Cache TTL in seconds (longest collection interval + 25% buffer)
        """
        # Find the longest collection interval from ScheduleFrequency
        max_multiplier = max(FREQUENCY_MULTIPLIERS.values())
        longest_interval = base_interval * max_multiplier

        # Add 25% buffer to ensure cache doesn't expire before collection
        cache_ttl = int(longest_interval * 1.25)

        return cache_ttl

    def __init__(self, base_interval: int = 60, ttl_seconds: Optional[int] = None):
        """
        Initialize configuration cache with ScheduleFrequency-aligned intervals

        Args:
            base_interval: Base collection interval from main collector (default 60s)
            ttl_seconds: Override cache TTL (calculated automatically if None)
        """
        self.base_interval = base_interval

        # Calculate collection intervals based on ScheduleFrequency mappings
        self.drive_config_interval = base_interval * FREQUENCY_MULTIPLIERS[ScheduleFrequency.LOW_FREQUENCY]
        self.volume_config_interval = base_interval * FREQUENCY_MULTIPLIERS[ScheduleFrequency.HIGH_FREQUENCY]
        self.system_config_interval = base_interval * FREQUENCY_MULTIPLIERS[ScheduleFrequency.LOW_FREQUENCY]
        self.pool_config_interval = base_interval * FREQUENCY_MULTIPLIERS[ScheduleFrequency.MEDIUM_FREQUENCY]

        # Calculate cache TTL automatically if not provided
        if ttl_seconds is None:
            ttl_seconds = self.calculate_cache_ttl(base_interval)

        self._cache = CacheManager(ttl_seconds=ttl_seconds)
        self.logger = logging.getLogger(__name__)

        self.logger.debug(f"ConfigCache initialized with base_interval={base_interval}s, ttl={ttl_seconds}s")
        self.logger.debug(f"Collection intervals: drives={self.drive_config_interval}s, "
                         f"volumes={self.volume_config_interval}s, "
                         f"systems={self.system_config_interval}s, "
                         f"pools={self.pool_config_interval}s")

    # Drive methods
    def store_drive(self, system_id: str, drive: DriveConfig) -> None:
        """Store a drive configuration"""
        key = f"{system_id}:{drive.id}"
        self._cache.set('drives', key, drive)

    def get_drive(self, system_id: str, drive_id: str) -> Optional[DriveConfig]:
        """Get a drive configuration by ID"""
        return self._cache.get('drives', f"{system_id}:{drive_id}")

    def get_all_drives(self, system_id: str) -> Dict[str, DriveConfig]:
        """Get all drives for a system"""
        all_drives = self._cache.get_all('drives')
        # Filter to only this system's drives
        return {k.split(':')[1]: v for k, v in all_drives.items()
                if k.startswith(f"{system_id}:")}

    def should_collect_drives(self, system_id: str) -> bool:
        """Check if drive configuration should be collected"""
        return self._cache.should_collect(f"drives:{system_id}", self.drive_config_interval)

    # Volume methods
    def store_volume(self, system_id: str, volume: VolumeConfig) -> None:
        """Store a volume configuration"""
        key = f"{system_id}:{volume.id}"
        self._cache.set('volumes', key, volume)

    def get_volume(self, system_id: str, volume_id: str) -> Optional[VolumeConfig]:
        """Get a volume configuration by ID"""
        return self._cache.get('volumes', f"{system_id}:{volume_id}")

    def get_all_volumes(self, system_id: str) -> Dict[str, VolumeConfig]:
        """Get all volumes for a system"""
        all_volumes = self._cache.get_all('volumes')
        # Filter to only this system's volumes
        return {k.split(':')[1]: v for k, v in all_volumes.items()
                if k.startswith(f"{system_id}:")}

    def should_collect_volumes(self, system_id: str) -> bool:
        """Check if volume configuration should be collected"""
        return self._cache.should_collect(f"volumes:{system_id}", self.volume_config_interval)

    # Storage Pool methods
    def store_storage_pool(self, system_id: str, pool: StoragePoolConfig) -> None:
        """Store a storage pool configuration"""
        key = f"{system_id}:{pool.id}"
        self._cache.set('pools', key, pool)

    def get_storage_pool(self, system_id: str, pool_id: str) -> Optional[StoragePoolConfig]:
        """Get a storage pool configuration by ID"""
        return self._cache.get('pools', f"{system_id}:{pool_id}")

    def should_collect_pools(self, system_id: str) -> bool:
        """Check if pool configuration should be collected"""
        return self._cache.should_collect(f"pools:{system_id}", self.pool_config_interval)

    # System methods
    def store_system(self, system: SystemConfig) -> None:
        """Store system configuration"""
        if system.wwn:
            self._cache.set('systems', system.wwn, system)
        else:
            self.logger.warning(f"SystemConfig has no WWN, cannot cache: {system}")

    def get_system(self, system_id: str) -> Optional[SystemConfig]:
        """Get system configuration"""
        return self._cache.get('systems', system_id)

    def should_collect_system(self, system_id: str) -> bool:
        """Check if system configuration should be collected"""
        return self._cache.should_collect(f"system:{system_id}", self.system_config_interval)

    # Helper methods to find relationships between objects
    def get_volumes_for_pool(self, system_id: str, pool_id: str) -> List[VolumeConfig]:
        """Get all volumes that belong to a storage pool"""
        volumes = self.get_all_volumes(system_id)
        return [v for v in volumes.values()
                if v.get_raw('volumeGroupRef') == pool_id]

    def get_drives_for_pool(self, system_id: str, pool_id: str) -> List[DriveConfig]:
        """Get all drives that belong to a storage pool"""
        # This might require additional logic depending on your data model
        # and how drives are associated with pools
        return []

    # Debug methods for system_id tracking
    def reset_system_set_counters(self) -> None:
        """Reset the system_id set operation counters for new iteration."""
        self._cache.reset_system_set_counters()

    def report_system_set_summary(self) -> None:
        """Report summary of system_id set operations for this iteration."""
        self._cache.report_system_set_summary()

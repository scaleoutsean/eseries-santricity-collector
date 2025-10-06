import time
import logging
from typing import Dict, Generic, Optional, TypeVar, Any

# Type variable for our cache generic
T = TypeVar('T')

class CacheManager(Generic[T]):
    """
    Generic cache manager for API response objects

    Provides:
    - Time-based expiration
    - Collection frequency control
    - Access to cached objects by ID and type
    """

    def __init__(self, ttl_seconds: int = 3600):
        """
        Initialize cache manager

        Args:
            ttl_seconds: Default time-to-live in seconds
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._timestamps: Dict[str, float] = {}
        self._ttl_seconds = ttl_seconds
        self._last_collection: Dict[str, float] = {}
        self.logger = logging.getLogger(__name__)

        # Debug counters for system_id tracking
        self._system_set_counters: Dict[str, int] = {}

    def set(self, cache_type: str, key: str, value: T) -> None:
        """
        Store an object in the cache

        Args:
            cache_type: Type of cached object (e.g., 'drives', 'volumes')
            key: Unique identifier for the object
            value: Object to cache
        """
        # Debug logging for system identification cache operations
        if cache_type in ['system_info', 'systems', 'system:config'] or 'system' in cache_type.lower():
            import inspect
            frame = inspect.currentframe()
            caller_info = []
            try:
                # Get caller stack to identify who is setting system info
                current_frame = frame
                for _ in range(1, 4):  # Check up to 3 levels up the call stack
                    if current_frame is None:
                        break
                    caller_frame = current_frame.f_back
                    if caller_frame is None:
                        break
                    caller_info.append({
                        'function': caller_frame.f_code.co_name,
                        'file': caller_frame.f_code.co_filename.split('/')[-1],
                        'line': caller_frame.f_lineno
                    })
                    current_frame = caller_frame
            except Exception:
                caller_info = [{'function': 'unknown', 'file': 'unknown', 'line': 0}]

            # Check if this is a duplicate set operation for the same key
            is_update = (cache_type in self._cache and key in self._cache[cache_type])
            existing_value = self._cache[cache_type][key] if is_update else None

            # Track frequency of system_id sets per key
            counter_key = f"{cache_type}:{key}"
            self._system_set_counters[counter_key] = self._system_set_counters.get(counter_key, 0) + 1
            set_count = self._system_set_counters[counter_key]

            # Log with warning if we're setting the same key multiple times (potential overwrite)
            if set_count > 1:
                self.logger.warning(f"CACHE_SET #{set_count}: {cache_type}[{key}] = {value} "
                                  f"(OVERWRITING existing: {existing_value}) "
                                  f"called by: {' -> '.join([f"{c['file']}:{c['function']}:{c['line']}" for c in caller_info])}")
            else:
                self.logger.debug(f"CACHE_SET #{set_count}: {cache_type}[{key}] = {value} "
                                f"called by: {' -> '.join([f"{c['file']}:{c['function']}:{c['line']}" for c in caller_info])}")

        if cache_type not in self._cache:
            self._cache[cache_type] = {}

        self._cache[cache_type][key] = value
        self._timestamps[f"{cache_type}:{key}"] = time.time()

    def get(self, cache_type: str, key: str) -> Optional[T]:
        """
        Retrieve an object from the cache

        Args:
            cache_type: Type of cached object
            key: Unique identifier for the object

        Returns:
            The cached object or None if not found or expired
        """
        if cache_type not in self._cache or key not in self._cache[cache_type]:
            return None

        # Check expiration
        timestamp_key = f"{cache_type}:{key}"
        if timestamp_key in self._timestamps:
            if time.time() - self._timestamps[timestamp_key] > self._ttl_seconds:
                # Expired
                del self._cache[cache_type][key]
                del self._timestamps[timestamp_key]
                return None

        return self._cache[cache_type][key]

    def get_all(self, cache_type: str) -> Dict[str, T]:
        """
        Get all non-expired objects of a specific type

        Args:
            cache_type: Type of cached objects to retrieve

        Returns:
            Dictionary of objects by key
        """
        if cache_type not in self._cache:
            return {}

        # Filter out expired items
        result = {}
        expired_keys = []

        for key, value in self._cache[cache_type].items():
            timestamp_key = f"{cache_type}:{key}"
            if timestamp_key in self._timestamps:
                if time.time() - self._timestamps[timestamp_key] > self._ttl_seconds:
                    expired_keys.append(key)
                else:
                    result[key] = value

        # Clean up expired items
        for key in expired_keys:
            del self._cache[cache_type][key]
            del self._timestamps[f"{cache_type}:{key}"]

        return result

    def should_collect(self, collection_type: str, interval_seconds: int) -> bool:
        """
        Determine if data collection should happen based on interval

        Args:
            collection_type: Type of collection (e.g., 'drives', 'volumes')
            interval_seconds: Minimum interval between collections

        Returns:
            True if collection should happen, False otherwise
        """
        current_time = time.time()
        last_time = self._last_collection.get(collection_type, 0)

        if current_time - last_time >= interval_seconds:
            self._last_collection[collection_type] = current_time
            return True
        return False

    def mark_collected(self, collection_type: str) -> None:
        """
        Mark a collection type as collected now

        Args:
            collection_type: Type of collection to mark
        """
        self._last_collection[collection_type] = time.time()

    def clear(self, cache_type: Optional[str] = None) -> None:
        """
        Clear cache entries

        Args:
            cache_type: Type to clear or None for all
        """
        if cache_type is None:
            self._cache = {}
            # Only clear timestamps that belong to cache entries
            self._timestamps = {k: v for k, v in self._timestamps.items() if k.split(":")[0] not in self._cache}
        elif cache_type in self._cache:
            # Remove all entries of this type
            keys = list(self._cache[cache_type].keys())
            for key in keys:
                timestamp_key = f"{cache_type}:{key}"
                if timestamp_key in self._timestamps:
                    del self._timestamps[timestamp_key]
            del self._cache[cache_type]

    def reset_system_set_counters(self) -> None:
        """Reset the system_id set operation counters for new iteration."""
        self._system_set_counters.clear()
        self.logger.debug("CACHE_DEBUG: Reset system set counters for new iteration")

    def report_system_set_summary(self) -> None:
        """Report summary of system_id set operations for this iteration."""
        if self._system_set_counters:
            self.logger.info("CACHE_SUMMARY: System set operations this iteration:")
            for key, count in self._system_set_counters.items():
                cache_type, cache_key = key.split(':', 1)
                current_value = self.get(cache_type, cache_key)
                status = "MULTIPLE_SETS" if count > 1 else "SINGLE_SET"
                self.logger.info(f"  {key}: {count} sets ({status}) - final value: {current_value}")
        else:
            self.logger.debug("CACHE_SUMMARY: No system set operations recorded this iteration")

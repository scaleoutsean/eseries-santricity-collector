"""
Batched JSON reader for timestamp-based file processing.
Handles grouping JSON files by timestamp and providing them in chronological batches.
"""

import os
import glob
import re
import logging
from typing import List, Optional, Tuple
from datetime import datetime
from itertools import groupby

logger = logging.getLogger(__name__)

class BatchedJsonReader:
    """
    Reader that groups JSON files by timestamp and provides them in chronological batches.
    Prevents flooding by processing files in time-ordered groups.
    """

    def __init__(self, directory: str, batch_size_minutes: int = 1, system_id_filter: Optional[str] = None):
        """
        Initialize the batched reader.

        Args:
            directory: Directory containing JSON files
            batch_size_minutes: Size of time batches in minutes (default: 1)
            system_id_filter: Optional system ID to filter files (only process files containing this system ID)
        """
        self.directory = directory
        self.batch_size_minutes = batch_size_minutes
        self.system_id_filter = system_id_filter
        self.batches = []
        self.current_batch_index = 0

        # Initialize batches on creation
        self._initialize_batches()

    def _extract_minute_from_filename(self, filename: str) -> int:
        """
        Extract minute from filename for grouping.
        Supports both new smart filenames and legacy formats.

        Args:
            filename: Path to the JSON file

        Returns:
            Minute timestamp for grouping (timestamp // 60)
        """
        # Try to match new smart filename format: category_endpoint_systemid_objectid_YYYYMMDDHHMM.json
        # or category_endpoint_systemid_YYYYMMDDHHMM.json
        match = re.search(r'_(\d{12})\.json$', filename)
        if match:
            try:
                timestamp_str = match.group(1)
                # YYYYMMDDHHMM format - convert to unix timestamp then minutes
                dt = datetime.strptime(timestamp_str, '%Y%m%d%H%M')
                return int(dt.timestamp()) // 60
            except Exception as e:
                logger.debug(f"Failed to parse new format timestamp from {filename}: {e}")

        # Try legacy format: unix timestamp or YYYYMMDDHHMM at end
        match = re.search(r'_(\d{10,12})(?:\.json)?$', filename)
        if match:
            try:
                val = match.group(1)
                if len(val) == 10:
                    # Unix timestamp - convert to minutes
                    return int(val) // 60
                elif len(val) == 12:
                    # YYYYMMDDHHMM format - convert to unix timestamp then minutes
                    dt = datetime.strptime(val, '%Y%m%d%H%M')
                    return int(dt.timestamp()) // 60
            except Exception as e:
                logger.debug(f"Failed to parse legacy timestamp from {filename}: {e}")

        # Fall back to file modification time
        return int(os.path.getmtime(filename)) // 60

    def _initialize_batches(self):
        """
        Initialize batches by finding all JSON files and grouping them by timestamp.
        """
        # File patterns using centralized measurement names from endpoint categorization
        # Format: <measurement_name>_<system_id>_[<object_id>_]<timestamp>.json
        # These patterns match the centralized get_measurement_name() output
        file_patterns = [
            # Performance endpoints (centralized naming)
            'performance_volume_statistics_*.json',
            'performance_drive_statistics_*.json',
            'performance_system_statistics_*.json',
            'performance_interface_statistics_*.json',
            'performance_controller_statistics_*.json',

            # Environmental endpoints (already correctly named)
            'env_power_*.json',
            'env_temperature_*.json',

            # Events endpoints (centralized naming)
            'events_system_failures_*.json',
            'events_lockdown_status_*.json',
            'events_parity_scan_jobs_*.json',
            'events_volume_copy_jobs_*.json',
            'events_*_*.json',  # Catch other event types

            # Configuration endpoints (centralized naming)
            'config_system_*.json',
            'config_controller_*.json',
            'config_hardware_*.json',
            'config_tray_*.json',
            'config_ethernet_interface_*.json',
            'config_interfaces_*.json',
            'config_storage_pools_*.json',
            'config_volumes_*.json',
            'config_volume_mappings_*.json',
            'config_drives_*.json',
            'config_hosts_*.json',
            'config_host_groups_*.json',

            # Snapshot configuration endpoints
            'snapshot_schedules_*.json',
            'snapshot_groups_*.json',
            'snapshot_volumes_*.json',
            'snapshot_images_*.json',
            'snapshot_groups_repository_utilization_*.json',

            # Legacy patterns (for backward compatibility during transition)
            'system_*.json',
            'analysed_volume_*.json',
            'analyzed_*.json',
            'controller_*.json',
            'drive_*.json',
            'volume_*.json',
        ]

        # Collect all matching files
        files = []
        for pattern in file_patterns:
            full_pattern = os.path.join(self.directory, pattern)
            found_files = glob.glob(full_pattern)
            files.extend(found_files)

        logger.info(f"BatchedJsonReader found {len(files)} total files in {self.directory}")

        # Apply system ID filter if specified (case-insensitive)
        if self.system_id_filter and self.system_id_filter.strip():
            original_count = len(files)
            files = [f for f in files if self.system_id_filter.lower() in os.path.basename(f).lower()]
            filtered_count = len(files)
            logger.info(f"BatchedJsonReader system ID filter '{self.system_id_filter}': "
                       f"{original_count} -> {filtered_count} files")
        else:
            filter_status = "not provided" if not self.system_id_filter else "empty"
            logger.info(f"BatchedJsonReader system ID filter {filter_status} - processing all files")

        if not files:
            filter_msg = f" (after system ID filter '{self.system_id_filter}')" if self.system_id_filter else ""
            logger.warning(f"No JSON files found in {self.directory}{filter_msg}")
            return

        # Sort files by timestamp minute, then by filename for consistency
        files.sort(key=lambda f: (self._extract_minute_from_filename(f), f))

        # Group files by minute timestamp
        # groupby returns an iterator, so we need to consume it immediately
        grouped = groupby(files, key=self._extract_minute_from_filename)
        self.batches = [(minute, list(group)) for minute, group in grouped]

        logger.info(f"BatchedJsonReader created {len(self.batches)} timestamp batches")

        # Log first few batches for debugging
        for i, (minute, batch) in enumerate(self.batches[:3]):
            readable_time = datetime.fromtimestamp(minute * 60).strftime('%Y-%m-%d %H:%M:%S')
            filenames = [os.path.basename(f) for f in batch[:3]]
            logger.info(f"  Batch {i+1}: minute {minute} ({readable_time}) - {len(batch)} files: {filenames}...")
            # DEBUG-log files starting with configuration_ for deeper insight
            if logger.isEnabledFor(logging.DEBUG):
                for f in batch:
                    if os.path.basename(f).startswith('configuration_'):
                        logger.debug(f"    Configuration file in batch: {os.path.basename(f)}")

    def get_current_batch(self) -> List[str]:
        """
        Get the current batch of files without advancing the index.
        Applies system ID filtering if configured.

        Returns:
            List of file paths for the current batch, or empty list if no more batches
        """
        if self.current_batch_index >= len(self.batches):
            return []

        minute, files = self.batches[self.current_batch_index]  # pylint: disable=unused-variable

        # Apply system ID filter to current batch if specified (case-insensitive)
        if self.system_id_filter:
            filtered_files = [f for f in files if self.system_id_filter.lower() in os.path.basename(f).lower()]
            logger.debug(f"get_current_batch: system ID filter applied - {len(files)} -> {len(filtered_files)} files")
            return filtered_files

        return files

    def get_next_batch(self) -> List[str]:
        """
        Get the next chronological batch of files and advance to the next batch.
        Applies system ID filtering if configured.

        Returns:
            List of file paths for the next batch, or empty list if no more batches
        """
        if self.current_batch_index >= len(self.batches):
            return []

        minute, files = self.batches[self.current_batch_index]
        readable_time = datetime.fromtimestamp(minute * 60).strftime('%Y-%m-%d %H:%M:%S')

        # Apply system ID filter to batch files if specified (case-insensitive)
        if self.system_id_filter:
            filtered_files = [f for f in files if self.system_id_filter.lower() in os.path.basename(f).lower()]
            logger.info(f"BatchedJsonReader serving batch {self.current_batch_index + 1}/{len(self.batches)}: "
                       f"minute {minute} ({readable_time}) with {len(filtered_files)} files (filtered from {len(files)})")
            self.current_batch_index += 1
            return filtered_files
        else:
            logger.info(f"BatchedJsonReader serving batch {self.current_batch_index + 1}/{len(self.batches)}: "
                       f"minute {minute} ({readable_time}) with {len(files)} files")
            self.current_batch_index += 1
            return files

    def advance_to_next_batch(self) -> bool:
        """
        Advance to the next batch without returning files.

        Returns:
            True if advanced to next batch, False if no more batches
        """
        if self.current_batch_index >= len(self.batches):
            return False

        minute, files = self.batches[self.current_batch_index]
        readable_time = datetime.fromtimestamp(minute * 60).strftime('%Y-%m-%d %H:%M:%S')

        logger.info(f"BatchedJsonReader advancing to batch {self.current_batch_index + 1}/{len(self.batches)}: "
                   f"minute {minute} ({readable_time}) with {len(files)} files")

        self.current_batch_index += 1
        return True

    def has_more_batches(self) -> bool:
        """
        Check if there are more batches available.

        Returns:
            True if more batches are available, False otherwise
        """
        return self.current_batch_index < len(self.batches)

    def get_current_batch_info(self) -> Optional[Tuple[int, str, int]]:
        """
        Get information about the current batch.

        Returns:
            Tuple of (batch_number, readable_time, file_count) or None if no current batch
        """
        if self.current_batch_index == 0 or self.current_batch_index > len(self.batches):
            return None

        # Get info for the batch we just served (current_batch_index - 1)
        batch_index = self.current_batch_index - 1
        minute, files = self.batches[batch_index]
        readable_time = datetime.fromtimestamp(minute * 60).strftime('%Y-%m-%d %H:%M:%S')

        return (batch_index + 1, readable_time, len(files))

    def get_total_batches(self) -> int:
        """
        Get the total number of batches.

        Returns:
            Total number of timestamp batches available
        """
        return len(self.batches)

    def reset(self):
        """
        Reset the reader to start from the first batch again.
        """
        self.current_batch_index = 0
        logger.info("BatchedJsonReader reset to first batch")

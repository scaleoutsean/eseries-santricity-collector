"""JSON Replay DataSource implementation.

Replays data from previously collected JSON files.
"""

import logging
import json
import os
import time
from typing import Dict, Any, Optional

from .base import DataSource, CollectionResult, CollectionType, SystemInfo
from ..cache.config_cache import ConfigCache
from ..read.batched_json_reader import BatchedJsonReader
from ..config.endpoint_categories import get_measurement_name


class JSONReplayDataSource(DataSource):
    """DataSource implementation for JSON file replay.

    This implementation handles:
    - Batched JSON file reading with proper system ID filtering
    - Single-threaded file access (eliminates filtering bugs)
    - System information extraction from JSON files
    - Temporal batch progression
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)

        # Configuration from app/main.py JSON setup
        self.json_directory = config.get('json_directory') or config.get('from_json')
        self.system_id_filter = config.get('system_id')  # WWN filter (was system_id_filter)

        # BatchedJsonReader state
        self.batched_reader = None
        # JSON replay uses BatchedJsonReader directly instead of ESeriesCollector
        self.config_scheduler: Optional[Any] = None  # Will be ConfigCollectionScheduler
        self.config_cache: Optional[Any] = None  # Will be ConfigCache

    def initialize(self) -> bool:
        """Initialize JSON replay with batched reader.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            if not self.json_directory:
                self.logger.error("JSON directory not configured")
                return False

            if not os.path.exists(self.json_directory):
                self.logger.error(f"JSON directory does not exist: {self.json_directory}")
                return False

            self.logger.info(f"Initializing JSON replay from directory: {self.json_directory}")

            # Initialize BatchedJsonReader directly for proper file handling
            self.batched_reader = BatchedJsonReader(
                directory=self.json_directory,
                system_id_filter=self.system_id_filter  # Critical: Apply system ID filtering
            )
            self.logger.info(f"Initialized BatchedJsonReader for directory: {self.json_directory}")

            # Initialize config collection scheduler
            from ..config.collection_schedules import ConfigCollectionScheduler
            interval = self.config.get('interval', 300)
            try:
                self.config_scheduler = ConfigCollectionScheduler(interval)
                self.logger.info(f"Initialized config collection scheduler with {interval}s base interval")
            except Exception as e:
                self.logger.error(f"Failed to initialize config scheduler: {e}")
                self.config_scheduler = None

            # Create centralized config cache
            self.config_cache = ConfigCache()            # Extract system info from config files if available (from app/main.py lines 859-881)
            if self.system_id_filter:
                # Try to extract real system name from system config file
                real_system_name = None
                try:
                    import glob
                    # Look for system config files matching our system ID
                    config_files = glob.glob(f"{self.json_directory}/{get_measurement_name('system_config')}_{self.system_id_filter}*.json")
                    if config_files:
                        # Use JsonReader to get normalized format (auto-unwraps raw_collector wrapper)
                        from ..read.json_reader import JsonReader
                        config_data = JsonReader.read_file(config_files[0])

                        # Use shared utility to extract system name (handles both old and new formats)
                        from ..utils.data_extraction import extract_system_name_from_config
                        real_system_name = extract_system_name_from_config(config_data)
                        if not real_system_name:
                            raise ValueError(f"No system name found in config file for system {self.system_id_filter}")

                        self.logger.info(f"Extracted real system name from config: {real_system_name}")

                        # Register with unified system context manager
                        from ..utils.system_context import system_context_manager
                        system_context_manager.register_system_from_json_replay(
                            self.system_id_filter, config_data
                        )
                except Exception as e:
                    self.logger.debug(f"Could not extract system name from config files: {e}")

                # Use real name if found, otherwise fail - no fallback allowed
                if not real_system_name:
                    raise ValueError(f"No system name found in config files for system {self.system_id_filter}")

                system_name = real_system_name

                self._system_info = SystemInfo(
                    wwn=self.system_id_filter,
                    name=system_name
                )
                self.logger.info(f"JSON replay mode initialized with system ID: {self.system_id_filter}, name: {system_name}")
            else:
                # No SYSTEM_ID specified in JSON replay mode - this is an error condition
                self.logger.error("SYSTEM_ID environment variable is required when FROM_JSON is enabled")
                self.logger.error("JSON replay mode requires explicit system identification to handle multi-system JSON files")
                self.logger.error("Please set SYSTEM_ID environment variable to the system WWN you want to process")
                self.logger.error("Example: SYSTEM_ID=6D039EA0004D00AA000000006652A086")

                # Check if we have JSON files from multiple systems to provide helpful guidance
                try:
                    import glob
                    system_config_pattern = os.path.join(self.json_directory, f'{get_measurement_name("system_config")}_*.json')
                    system_config_files = glob.glob(system_config_pattern)

                    if len(system_config_files) > 1:
                        self.logger.error(f"Found {len(system_config_files)} different systems in JSON directory:")
                        for config_file in system_config_files[:5]:  # Show first 5
                            filename = os.path.basename(config_file)
                            # Extract WWN from filename: config_system_WWN_timestamp.json
                            parts = filename.split('_')
                            if len(parts) >= 4:
                                wwn = parts[3]
                                self.logger.error(f"  - System WWN: {wwn}")
                        self.logger.error("Use one of these WWNs as SYSTEM_ID to specify which system to process")
                    elif len(system_config_files) == 1:
                        filename = os.path.basename(system_config_files[0])
                        parts = filename.split('_')
                        if len(parts) >= 4:
                            wwn = parts[3]
                            self.logger.error(f"Found single system in JSON directory - set SYSTEM_ID={wwn}")

                except Exception as e:
                    self.logger.debug(f"Could not analyze system files for guidance: {e}")

                raise ValueError("SYSTEM_ID is required for JSON replay mode. Cannot proceed with mixed-system JSON files without explicit system selection.")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize JSONReplayDataSource: {e}")
            return False

    def _inject_system_info(self, data_list):
        """Inject system WWN and name into each performance/config/event record."""
        # Use the centralized system context manager to inject a canonical set of
        # system identification tags (storage_system_name, storage_system_wwn,
        # system_name, system_wwn, sys_name, sys_id, etc.). This ensures JSON
        # replay produces records equivalent to Live API ingestion.
        if not data_list or not self._system_info:
            return

        try:
            from ..utils.system_context import system_context_manager
            system_context_manager.inject_system_context(data_list, self._system_info.wwn)
            self.logger.debug(f"Injected canonical system context for WWN: {self._system_info.wwn} into {len(data_list)} records")
        except Exception as e:
            # Fallback: best-effort minimal injection to avoid losing system id entirely
            system_wwn = self._system_info.wwn
            system_name = getattr(self._system_info, 'name', None)
            for record in data_list:
                if isinstance(record, dict):
                    record.setdefault('system_id', system_wwn)
                    if system_name:
                        record.setdefault('storage_system_name', system_name)
            self.logger.debug(f"Fallback injected basic system info (WWN: {system_wwn}) into {len(data_list)} records due to: {e}")

    def collect_performance_data(self) -> CollectionResult:
        """Collect all performance data types using BatchedJsonReader."""
        try:
            if not self.batched_reader:
                return CollectionResult(
                    collection_type=CollectionType.PERFORMANCE,
                    data={},
                    success=False,
                    error_message="BatchedJsonReader not initialized"
                )

            self.logger.info("Starting performance data collection using BatchedJsonReader...")
            start_time = time.time()

            # Get current batch of files from BatchedJsonReader
            current_batch = self.batched_reader.get_current_batch()
            if not current_batch:
                self.logger.info("No performance data batch available")
                return CollectionResult(
                    collection_type=CollectionType.PERFORMANCE,
                    data={},
                    success=True,
                    error_message=None
                )

            # Import JSON reader utility
            from ..read.json_reader import JsonReader

            # Collect different performance data types using BatchedJsonReader
            performance_data = {}

            # Volume statistics
            volume_files = [f for f in current_batch if 'performance_volume_statistics' in f.lower()]
            if volume_files:
                volume_data = []
                for file_path in volume_files:
                    file_data = JsonReader.read_file(file_path)
                    if not file_data:
                        continue

                    # Use shared data extraction utility
                    from ..utils.data_extraction import extract_analyzed_statistics_data
                    extracted_records = extract_analyzed_statistics_data(
                        file_data, 'analyzed_volume_statistics', 'json_replay'
                    )
                    volume_data.extend(extracted_records)

                if volume_data:
                    # Inject system_id into performance data
                    self._inject_system_info(volume_data)
                    performance_data['performance_volume_statistics'] = volume_data
                    self.logger.info(f"Collected {len(volume_data)} volume statistics records")

            # Drive statistics
            drive_files = [f for f in current_batch if 'performance_drive_statistics' in f.lower()]
            if drive_files:
                drive_data = []
                for file_path in drive_files:
                    file_data = JsonReader.read_file(file_path)
                    if not file_data:
                        continue

                    # Use shared data extraction utility
                    from ..utils.data_extraction import extract_analyzed_statistics_data
                    extracted_records = extract_analyzed_statistics_data(
                        file_data, 'analyzed_drive_statistics', 'json_replay'
                    )
                    drive_data.extend(extracted_records)

                if drive_data:
                    # Inject system_id into performance data
                    self._inject_system_info(drive_data)
                    performance_data['performance_drive_statistics'] = drive_data
                    self.logger.info(f"Collected {len(drive_data)} drive statistics records")

            # System statistics
            system_files = [f for f in current_batch if 'performance_system_statistics' in f.lower()]
            if system_files:
                system_data = []
                for file_path in system_files:
                    file_data = JsonReader.read_file(file_path)
                    if not file_data:
                        continue

                    # Use shared data extraction utility
                    from ..utils.data_extraction import extract_analyzed_statistics_data
                    extracted_records = extract_analyzed_statistics_data(
                        file_data, 'analyzed_system_statistics', 'json_replay'
                    )
                    system_data.extend(extracted_records)

                if system_data:
                    # Inject system_id into performance data
                    self._inject_system_info(system_data)
                    performance_data['performance_system_statistics'] = system_data
                    self.logger.info(f"Collected {len(system_data)} system statistics records")

            # Interface statistics
            interface_files = [f for f in current_batch if 'performance_interface_statistics' in f.lower()]
            if interface_files:
                interface_data = []
                for file_path in interface_files:
                    file_data = JsonReader.read_file(file_path)

                    # Use shared data extraction utility
                    from ..utils.data_extraction import extract_analyzed_statistics_data
                    extracted_records = extract_analyzed_statistics_data(
                        file_data, 'analyzed_interface_statistics', 'json_replay'
                    )
                    interface_data.extend(extracted_records)

                if interface_data:
                    # Inject system_id into performance data
                    self._inject_system_info(interface_data)
                    performance_data['performance_interface_statistics'] = interface_data
                    self.logger.info(f"Collected {len(interface_data)} interface statistics records")

            # Controller statistics (note: both analyzed and analysed spellings)
            controller_files = [f for f in current_batch if 'performance_controller_statistics' in f.lower()]
            if controller_files:
                controller_data = []
                for file_path in controller_files:
                    file_data = JsonReader.read_file(file_path)

                    # Use shared data extraction utility
                    from ..utils.data_extraction import extract_analyzed_statistics_data
                    extracted_records = extract_analyzed_statistics_data(
                        file_data, 'analyzed_controller_statistics', 'json_replay'
                    )
                    controller_data.extend(extracted_records)

                if controller_data:
                    # Inject system_id into performance data
                    self._inject_system_info(controller_data)
                    performance_data['performance_controller_statistics'] = controller_data
                    self.logger.info(f"Collected {len(controller_data)} controller statistics records")

            duration = time.time() - start_time
            total_records = sum(len(data) for data in performance_data.values())
            self.logger.info(f"Performance data collection completed: {total_records} total records in {duration:.2f}s using BatchedJsonReader")

            return CollectionResult(
                collection_type=CollectionType.PERFORMANCE,
                data=performance_data,
                success=True,
                error_message=None
            )

        except Exception as e:
            self.logger.error(f"Failed to collect performance data: {e}")
            return CollectionResult(
                collection_type=CollectionType.PERFORMANCE,
                data={},
                success=False,
                error_message=str(e)
            )

    def collect_configuration_data(self) -> CollectionResult:
        """Collect all configuration data types from current JSON batch."""
        try:
            if not self.config_scheduler:
                return CollectionResult(
                    collection_type=CollectionType.CONFIGURATION,
                    data={},
                    success=True,
                    metadata={'source': 'json_replay', 'status': 'no_scheduler'}
                )

            # Get config types to collect on this iteration (from app/main.py JSON config collector)
            collections_needed = self.config_scheduler.get_config_types_for_collection()

            if collections_needed:
                self.logger.info(f"JSON mode: Scheduler indicates collection needed for {len(collections_needed)} frequencies")
                for frequency, config_types in collections_needed.items():
                    self.logger.info(f"  {frequency.value}: {config_types}")

                # Actually collect the config data from JSON files (similar to API mode)
                collected_data = {}
                for frequency, config_types in collections_needed.items():
                    for config_type in config_types:
                        try:
                            data = self._collect_config_type_from_json(config_type)
                            if data:
                                collected_data[config_type] = data
                                self.logger.info(f"JSON mode: Collected {len(data) if isinstance(data, list) else 1} items for {config_type}")
                        except Exception as e:
                            self.logger.error(f"JSON mode: Failed to collect {config_type}: {e}")

                return CollectionResult(
                    collection_type=CollectionType.CONFIGURATION,
                    data=collected_data,
                    success=True,
                    metadata={
                        'source': 'json_replay',
                        'status': 'scheduled_collection',
                        'iteration': self.config_scheduler.iteration_count,
                        'collections': {freq.value: types for freq, types in collections_needed.items()}
                    }
                )
            else:
                self.logger.info(f"JSON mode: No config collection needed on iteration {self.config_scheduler.iteration_count}")
                return CollectionResult(
                    collection_type=CollectionType.CONFIGURATION,
                    data={},
                    success=True,
                    metadata={
                        'source': 'json_replay',
                        'status': 'no_collection_needed',
                        'iteration': self.config_scheduler.iteration_count
                    }
                )

        except Exception as e:
            self.logger.error(f"Failed to collect configuration data from JSON: {e}")
            return CollectionResult(
                collection_type=CollectionType.CONFIGURATION,
                data={},
                success=False,
                error_message=str(e)
            )

    def _collect_config_type_from_json(self, config_type: str):
        """Collect a specific configuration type from JSON files."""
        try:
            if not self.batched_reader:
                self.logger.error("BatchedJsonReader not initialized")
                return []

            # Import model classes locally to avoid circular imports
            from ..schema.models import (
                VolumeConfig, VolumeMappingsConfig, HostConfig, StoragePoolConfig,
                HostGroupsConfig, SystemConfig, DriveConfig, ControllerConfig,
                EthernetConfig, InterfaceConfig, TrayConfig, SnapshotImages
            )

            # Use JsonReader directly to read configuration files with centralized naming
            from ..read.json_reader import JsonReader

            # Map to centralized file prefixes using get_measurement_name
            if config_type == "VolumeConfig":
                return self._collect_config_from_files(get_measurement_name('volumes_config'), VolumeConfig)
            elif config_type == "VolumeMappingsConfig":
                return self._collect_config_from_files(get_measurement_name('volume_mappings_config'), VolumeMappingsConfig)
            elif config_type == "HostConfig":
                return self._collect_config_from_files(get_measurement_name('hosts'), HostConfig)
            elif config_type == "StoragePoolConfig":
                return self._collect_config_from_files(get_measurement_name('storage_pools'), StoragePoolConfig)
            elif config_type == "HostGroupsConfig":
                return self._collect_config_from_files(get_measurement_name('host_groups'), HostGroupsConfig)
            elif config_type == "SystemConfig":
                return self._collect_config_from_files(get_measurement_name('system_config'), SystemConfig)
            elif config_type == "DriveConfig":
                return self._collect_config_from_files(get_measurement_name('drive_config'), DriveConfig)
            elif config_type == "ControllerConfig":
                return self._collect_config_from_files(get_measurement_name('controller_config'), ControllerConfig)
            elif config_type == "EthernetConfig":
                return self._collect_config_from_files(get_measurement_name('ethernet_interface_config'), EthernetConfig)
            elif config_type == "InterfaceConfig":
                return self._collect_config_from_files(get_measurement_name('interfaces_config'), InterfaceConfig)
            elif config_type == "TrayConfig":
                return self._collect_config_from_files(get_measurement_name('tray_config'), TrayConfig)
            elif config_type == "AsyncMirrorsConfig":
                return self._collect_config_from_files('async_mirrors', None)  # No mapping needed, use as-is
            elif config_type == "HardwareConfig":
                # Hardware inventory not stored in InfluxDB - used only for internal relationship mapping
                return []
            elif config_type == "SnapshotConfig":
                return self._collect_config_from_files('snapshot_images', SnapshotImages)
            elif config_type == "VolumeCGMembersConfig":
                # Volume consistency group members - use volume config for now
                return []
            elif config_type == "SnapshotConfig":
                # Handle snapshot config if supported
                return []
            elif config_type == "VolumeCGMembersConfig":
                # Handle volume consistency group members if supported
                return []
            else:
                self.logger.warning(f"JSON mode: Unknown config type: {config_type}")
                return []
        except Exception as e:
            self.logger.error(f"JSON mode: Error collecting {config_type}: {e}")
            return []

    def _collect_config_from_files(self, file_prefix: str, model_class):
        """Collect configuration data from JSON files with the given prefix."""
        try:
            from ..read.json_reader import JsonReader

            # Get current batch files
            current_files = self.batched_reader.get_current_batch()
            self.logger.debug(f"Looking for prefix '{file_prefix}' in {len(current_files)} files")
            self.logger.debug(f"First 3 files: {[str(f) for f in current_files[:3]]}")

            matching_files = [f for f in current_files if file_prefix in str(f)]

            if not matching_files:
                self.logger.debug(f"No files found matching prefix: {file_prefix}")
                self.logger.debug(f"Available files that might match: {[str(f) for f in current_files if 'config' in str(f)][:5]}")
                return []

            all_data = []
            for file_path in matching_files:
                try:
                    # Read file data
                    file_data = JsonReader.read_file(file_path)
                    if not file_data:
                        continue

                    # Use shared data extraction utility for configuration data
                    from ..utils.data_extraction import extract_configuration_data
                    config_items = extract_configuration_data(
                        file_data, file_prefix, 'json_replay'
                    )
                    all_data.extend(config_items)
                except Exception as e:
                    self.logger.debug(f"Failed to read {file_path}: {e}")
                    continue

            # Inject system WWN into all config records
            if all_data:
                self._inject_system_info(all_data)
                self.logger.debug(f"Injected system info into {len(all_data)} {file_prefix} records")

            return all_data

        except Exception as e:
            self.logger.error(f"Failed to collect config from files with prefix {file_prefix}: {e}")
            return []

    def collect_event_data(self) -> CollectionResult:
        """Collect all event/alert data types from current JSON batch.

        Note: Lockdown status is properly categorized as an event here too.
        """
        try:
            # Collect events from JSON files in current batch
            self.logger.info("Starting event data collection from JSON...")
            start_time = time.time()

            event_data = {
                'events_lockdown_status': [],
                'events_system_failures': [],
                'events_parity_scan_jobs': [],
                'events_volume_copy_jobs': []
            }

            # Get current batch files
            if not self.batched_reader:
                return CollectionResult(
                    collection_type=CollectionType.EVENTS,
                    data=event_data,
                    success=True,
                    metadata={'source': 'json_replay', 'message': 'no_batch_reader'}
                )

            current_files = self.batched_reader.get_current_batch()
            events_collected = 0

            for file_path in current_files:
                file_name = os.path.basename(file_path)

                try:
                    # System failures (support both old and new naming)
                    if 'events_system_failures_' in file_name and file_name.endswith('.json'):
                        with open(file_path, 'r') as f:
                            failures_wrapper = json.load(f)

                        # Handle raw_collector wrapper format - extract actual data
                        failures_data = failures_wrapper.get('data', failures_wrapper)

                        if isinstance(failures_data, list) and failures_data:
                            # Inject canonical system context into each failure record
                            try:
                                from ..utils.system_context import system_context_manager
                                system_context_manager.inject_system_context(failures_data, self.system_id_filter)
                            except Exception:
                                for failure in failures_data:
                                    if isinstance(failure, dict):
                                        failure.setdefault('system_id', self.system_id_filter)
                                        failure.setdefault('storage_system_name', 'json_replay_system')
                            event_data['events_system_failures'].extend(failures_data)
                            events_collected += len(failures_data)

                    # Lockdown status (support both old and new naming)
                    elif 'events_lockdown_status_' in file_name and file_name.endswith('.json'):
                        with open(file_path, 'r') as f:
                            lockdown_wrapper = json.load(f)

                        # Handle raw_collector wrapper format - extract actual data
                        lockdown_data = lockdown_wrapper.get('data', lockdown_wrapper)

                        if isinstance(lockdown_data, dict):
                            # Add canonical system context to the lockdown record
                            try:
                                from ..utils.system_context import system_context_manager
                                system_context_manager.inject_system_context([lockdown_data], self.system_id_filter)
                            except Exception:
                                lockdown_data.setdefault('system_id', self.system_id_filter)
                                lockdown_data.setdefault('storage_system_name', lockdown_data.get('storageSystemLabel', 'json_replay_system'))
                            event_data['events_lockdown_status'].append(lockdown_data)
                            events_collected += 1

                    # Parity scan jobs (may be empty arrays often)
                    elif 'parity_scan_job' in file_name and file_name.endswith('.json'):
                        with open(file_path, 'r') as f:
                            job_data = json.load(f)
                        if isinstance(job_data, list) and job_data:
                            # Inject canonical system context
                            try:
                                from ..utils.system_context import system_context_manager
                                system_context_manager.inject_system_context(job_data, self.system_id_filter)
                            except Exception:
                                for job in job_data:
                                    if isinstance(job, dict):
                                        job.setdefault('system_id', self.system_id_filter)
                                        job.setdefault('system_wwn', self.system_id_filter)
                                        job.setdefault('storage_system_name', 'json_replay_system')
                            event_data['events_parity_scan_jobs'].extend(job_data)
                            events_collected += len(job_data)

                    # Volume copy jobs (may be empty arrays often)
                    elif 'volume_copy_job' in file_name and file_name.endswith('.json'):
                        with open(file_path, 'r') as f:
                            job_data = json.load(f)
                        if isinstance(job_data, list) and job_data:
                            # Inject canonical system context
                            try:
                                from ..utils.system_context import system_context_manager
                                system_context_manager.inject_system_context(job_data, self.system_id_filter)
                            except Exception:
                                for job in job_data:
                                    if isinstance(job, dict):
                                        job.setdefault('system_id', self.system_id_filter)
                                        job.setdefault('system_wwn', self.system_id_filter)
                                        job.setdefault('storage_system_name', 'json_replay_system')
                            event_data['events_volume_copy_jobs'].extend(job_data)
                            events_collected += len(job_data)

                except Exception as e:
                    self.logger.warning(f"Failed to read event file {file_name}: {e}")
                    continue

            collection_time = time.time() - start_time
            self.logger.info(f"Event collection completed in {collection_time:.2f}s, collected {events_collected} events")
            self.logger.info(f"Event breakdown: {len(event_data['events_system_failures'])} failures, {len(event_data['events_lockdown_status'])} lockdown, {len(event_data['events_parity_scan_jobs'])} parity jobs, {len(event_data['events_volume_copy_jobs'])} volume jobs")

            return CollectionResult(
                collection_type=CollectionType.EVENTS,
                data=event_data,
                success=True,
                metadata={
                    'source': 'json_replay',
                    'collection_time_seconds': collection_time,
                    'events_collected': events_collected
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to collect event data from JSON: {e}")
            return CollectionResult(
                collection_type=CollectionType.EVENTS,
                data={},
                success=False,
                error_message=str(e)
            )

    def collect_environmental_data(self) -> CollectionResult:
        """Collect environmental monitoring data from current JSON batch."""
        try:
            if not self.batched_reader:
                return CollectionResult(
                    collection_type=CollectionType.ENVIRONMENTAL,
                    data={},
                    success=False,
                    error_message="BatchedReader not initialized"
                )

            # Port environmental collection logic from app/main.py lines 1322-1380
            self.logger.info("Starting environmental monitoring collection from JSON...")
            env_start_time = time.time()

            # Read environmental JSON files using the batched reader
            env_power_data = []
            env_temp_data = []

            # Get current batch files
            current_files = self.batched_reader.get_current_batch()

            for file_path in current_files:
                file_name = os.path.basename(file_path)

                # Check if this is an environmental data file
                if 'env_power' in file_name and file_name.endswith('.json'):
                    try:
                        with open(file_path, 'r') as f:
                            import json
                            power_json_data = json.load(f)

                        # Handle raw_collector wrapper format - extract actual data
                        actual_data = power_json_data.get('data', power_json_data)

                        if actual_data.get('returnCode') == 'ok' and 'energyStarData' in actual_data:
                            # Convert to the format expected by symbols_collector processing
                            power_data = {'measurement': 'power', 'data': actual_data['energyStarData']}
                            env_power_data.append(power_data)
                    except Exception as e:
                        self.logger.warning(f"Failed to read power file {file_name}: {e}")

                elif 'env_temperature' in file_name and file_name.endswith('.json'):
                    try:
                        with open(file_path, 'r') as f:
                            import json
                            temp_json_data = json.load(f)

                        # Handle raw_collector wrapper format - extract actual data
                        actual_data = temp_json_data.get('data', temp_json_data)

                        if actual_data.get('returnCode') == 'ok' and 'thermalSensorData' in actual_data:
                            # Convert to the format expected by symbols_collector processing
                            temp_data = {'measurement': 'temp', 'data': actual_data['thermalSensorData']}
                            env_temp_data.append(temp_data)
                    except Exception as e:
                        self.logger.warning(f"Failed to read temperature file {file_name}: {e}")

            env_time = time.time() - env_start_time
            total_env_records = len(env_power_data) + len(env_temp_data)
            self.logger.info(f"Environmental monitoring collection completed in {env_time:.2f}s, collected {total_env_records} measurements")
            self.logger.info(f"Environmental breakdown: {len(env_power_data)} power measurements, {len(env_temp_data)} temperature measurements")

            # Inject system WWN into environmental data
            if env_power_data:
                self._inject_system_info(env_power_data)
                self.logger.debug(f"Injected system info into {len(env_power_data)} power records")

            if env_temp_data:
                self._inject_system_info(env_temp_data)
                self.logger.debug(f"Injected system info into {len(env_temp_data)} temperature records")

            environmental_data = {
                'env_power': env_power_data,
                'env_temperature': env_temp_data
            }

            return CollectionResult(
                collection_type=CollectionType.ENVIRONMENTAL,
                data=environmental_data,
                success=True,
                metadata={
                    'source': 'json_replay',
                    'collection_time_seconds': env_time,
                    'power_measurements': len(env_power_data),
                    'temperature_measurements': len(env_temp_data)
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to collect environmental data from JSON: {e}")
            return CollectionResult(
                collection_type=CollectionType.ENVIRONMENTAL,
                data={},
                success=False,
                error_message=str(e)
            )

    def advance_batch(self) -> bool:
        """Advance to the next batch of JSON files.

        Returns:
            True if batch advanced successfully, False if no more batches
        """
        try:
            if not self.batched_reader:
                self.logger.error("BatchedReader not initialized")
                return False

            # Port batch advancement from app/main.py
            batch_advanced = self.batched_reader.advance_to_next_batch()
            self.logger.info(f"Advanced to next batch: {batch_advanced}")
            return batch_advanced
        except Exception as e:
            self.logger.error(f"Failed to advance JSON batch: {e}")
            return False

    def has_more_batches(self) -> bool:
        """Check if more batches are available.

        Returns:
            True if more batches available, False otherwise
        """
        try:
            if not self.batched_reader:
                return False
            return self.batched_reader.has_more_batches()
        except Exception as e:
            self.logger.error(f"Error checking for more batches: {e}")
            return False

    def get_batch_info(self) -> Dict[str, Any]:
        """Get batch information for status reporting."""
        try:
            if not self.batched_reader:
                return {'available_batches': 0, 'batch_window_minutes': 0, 'total_files': 0}
            return {
                'available_batches': self.batched_reader.get_total_batches(),
                'total_files': len(self.batched_reader.get_current_batch())
            }
        except Exception as e:
            self.logger.error(f"Error getting batch info: {e}")
            return {'available_batches': 0, 'batch_window_minutes': 0, 'total_files': 0}

    def increment_scheduler_iteration(self) -> None:
        """Increment the config scheduler iteration counter."""
        if self.config_scheduler:
            self.config_scheduler.increment_iteration()
            self.logger.info(f"Config scheduler iteration: {self.config_scheduler.iteration_count}")

    def cleanup(self) -> None:
        """Clean up JSON replay resources."""
        # JSON replay doesn't need cleanup like API sessions
        pass
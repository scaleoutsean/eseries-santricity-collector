"""Main collector orchestration logic.

Replaces the complex dual-path logic in app/main.py with clean
DataSource pattern architecture.
"""

import logging
import os
import time
from typing import Optional, Dict, Any, List

from ..datasources.base import DataSource, CollectionResult, CollectionType
from ..datasources.live_api import LiveAPIDataSource
from ..datasources.json_replay import JSONReplayDataSource
from ..config.endpoint_categories import (
    get_endpoint_category, get_enrichment_processor, EndpointCategory,
    get_collection_behavior, get_endpoints_by_category
)
from .config import CollectorConfig
from .writer_config import WriterConfig


class MetricsCollector:
    """Main orchestrator for E-Series metrics collection.

    Provides clean interface that eliminates dual-path maintenance
    burden from app/main.py by using DataSource pattern.
    """

    def __init__(self, config: CollectorConfig, writer_config: Optional[WriterConfig] = None):
        """Initialize collector with configuration.

        Args:
            config: Collector configuration object
            writer_config: Writer configuration object (optional, can be created later)
        """
        self.config = config
        self.writer_config = writer_config
        self.logger = logging.getLogger(__name__)
        self.datasource: Optional[DataSource] = None
        self.writer = None  # Will be initialized on first use

        # Statistics tracking
        self.collections_completed = 0
        self.last_collection_time: Optional[float] = None

    def initialize(self) -> bool:
        """Initialize the collector system.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Create appropriate DataSource based on configuration
            if self.config.use_json_replay:
                self.logger.info("Initializing JSON replay mode")
                self.datasource = JSONReplayDataSource(self.config.to_dict())
            else:
                self.logger.info("Initializing live API mode")
                self.datasource = LiveAPIDataSource(self.config.to_dict())

            # Initialize the selected datasource
            if not self.datasource.initialize():
                self.logger.error("Failed to initialize datasource")
                return False

            self.logger.info(f"Collector initialized successfully in {'JSON replay' if self.config.use_json_replay else 'live API'} mode")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize collector: {e}")
            return False

    def set_writer_config(self, writer_config: WriterConfig) -> None:
        """Set the writer configuration after system discovery.

        Args:
            writer_config: Writer configuration with proper system identification
        """
        self.writer_config = writer_config
        self.logger.info(f"Writer configuration set with system: {writer_config.system_id}")

    def collect_all_data(self) -> Dict[CollectionType, CollectionResult]:
        """Collect all enabled data types from the datasource.

        Returns:
            Dictionary mapping collection types to their results
        """
        results = {}

        if not self.datasource:
            self.logger.error("Datasource not initialized")
            return results

        # Collect configuration data FIRST (ensures batched reader state is fresh for both JSON replay and live API)
        # Config data is mandatory for proper enrichment
        try:
            config_result = self.datasource.collect_configuration_data()
            results[CollectionType.CONFIGURATION] = config_result

            if config_result.success:
                self.logger.info("Configuration data collected successfully")
            else:
                self.logger.warning(f"Configuration data collection failed: {config_result.error_message}")
        except Exception as e:
            self.logger.error(f"Configuration data collection error: {e}")
            results[CollectionType.CONFIGURATION] = CollectionResult(
                collection_type=CollectionType.CONFIGURATION,
                data={},
                success=False,
                error_message=str(e)
            )

        # Small delay to ensure configuration data is processed before other collections
        time.sleep(2)

        # Collect performance data (always enabled for E-Series)
        try:
            performance_result = self.datasource.collect_performance_data()
            results[CollectionType.PERFORMANCE] = performance_result

            if performance_result.success:
                self.logger.info("Performance data collected successfully")
            else:
                self.logger.warning(f"Performance data collection failed: {performance_result.error_message}")
        except Exception as e:
            self.logger.error(f"Performance data collection error: {e}")
            results[CollectionType.PERFORMANCE] = CollectionResult(
                collection_type=CollectionType.PERFORMANCE,
                data={},
                success=False,
                error_message=str(e)
            )

        # Collect event data if enabled
        if self.config.include_events:
            try:
                event_result = self.datasource.collect_event_data()
                results[CollectionType.EVENTS] = event_result

                if event_result.success:
                    self.logger.info("Event data collected successfully")
                else:
                    self.logger.warning(f"Event data collection failed: {event_result.error_message}")
            except Exception as e:
                self.logger.error(f"Event data collection error: {e}")
                results[CollectionType.EVENTS] = CollectionResult(
                    collection_type=CollectionType.EVENTS,
                    data={},
                    success=False,
                    error_message=str(e)
                )

        # Collect environmental data if enabled
        if self.config.include_environmental:
            try:
                env_result = self.datasource.collect_environmental_data()
                results[CollectionType.ENVIRONMENTAL] = env_result

                if env_result.success:
                    self.logger.info("Environmental data collected successfully")
                else:
                    self.logger.warning(f"Environmental data collection failed: {env_result.error_message}")
            except Exception as e:
                self.logger.error(f"Environmental data collection error: {e}")
                results[CollectionType.ENVIRONMENTAL] = CollectionResult(
                    collection_type=CollectionType.ENVIRONMENTAL,
                    data={},
                    success=False,
                    error_message=str(e)
                )

        return results

    def process_and_write_data(self, collection_results: Dict[CollectionType, CollectionResult]) -> bool:
        """Process collected data through enrichment and write to output.

        Args:
            collection_results: Results from collect_all_data()

        Returns:
            True if processing/writing successful, False otherwise
        """
        try:
            # Initialize enrichment processor (using local collector enrichment)
            from ..enrichment.processor import EnrichmentProcessor

            # Get system info from datasource
            sys_info = self.datasource.get_system_info() if self.datasource else None
            sys_info_dict = {'name': sys_info.name, 'wwn': sys_info.wwn} if sys_info else {'name': 'unknown', 'wwn': 'unknown'}

            # Note: EnrichmentProcessor will be created after config data is collected
            enrichment_processor = None

            # Process each collection type
            enriched_data = {}
            config_data = {}
            event_data = {}

            # Extract performance data first (to be processed after enrichment processor is created)
            perf_result_data = None
            if CollectionType.PERFORMANCE in collection_results:
                perf_result = collection_results[CollectionType.PERFORMANCE]
                if perf_result.success and perf_result.data:
                    perf_result_data = perf_result.data
                    self.logger.info(f"Performance data extracted: {list(perf_result_data.keys()) if perf_result_data else 'empty'}")

            # Merge environmental data with performance data for processing
            if CollectionType.ENVIRONMENTAL in collection_results:
                env_result = collection_results[CollectionType.ENVIRONMENTAL]
                if env_result.success and env_result.data:
                    env_data = env_result.data
                    self.logger.info(f"Environmental data extracted: {list(env_data.keys()) if env_data else 'empty'}")
                    if perf_result_data is None:
                        perf_result_data = {}
                    perf_result_data.update(env_data)
                    self.logger.info(f"Merged environmental data into performance processing pipeline")

            # Extract configuration data (from app/main.py lines 1720-1780)
            config_data = None
            if CollectionType.CONFIGURATION in collection_results:
                config_result = collection_results[CollectionType.CONFIGURATION]
                if config_result.success:
                    config_data = config_result.data
                    self.logger.info(f"Configuration data extracted: {list(config_data.keys()) if config_data else 'empty'}")

            # Create enrichment processor with config data now that it's available
            # Create a mock config collector for enrichment processor
            class MockConfigCollector:
                def __init__(self):
                    from ..cache.config_cache import ConfigCache
                    self.config_cache = ConfigCache()
                    # Add mock eseries_collector to prevent enrichment processor loading errors
                    self.eseries_collector = None

            # Initialize enrichment processor with pre-collected config data
            enrichment_processor = EnrichmentProcessor(
                MockConfigCollector(),
                from_json=self.config.use_json_replay,
                sys_info=sys_info_dict,
                config_data=config_data  # Pass the collected config data
            )
            self.logger.info(f"EnrichmentProcessor created with config_data: {list(config_data.keys()) if config_data else 'None'}")

            # Now process performance data with the enrichment processor
            if perf_result_data:
                self.logger.info("Processing and enriching performance data...")

                # Process each performance type separately
                for perf_type, perf_records in perf_result_data.items():
                    if isinstance(perf_records, list) and len(perf_records) > 0:
                        # Skip environmental data from performance enrichment - temp=128.0 means "sensor OK status"
                        if perf_type.startswith('env_'):
                            self.logger.info(f"Skipping enrichment for environmental data: {perf_type} ({len(perf_records)} records)")
                            enriched_data[perf_type] = perf_records
                        else:
                            self.logger.info(f"Enriching {perf_type}: {len(perf_records)} records")
                            enriched_records = enrichment_processor.process(perf_records, measurement_type=perf_type)
                            enriched_data[perf_type] = enriched_records
                            self.logger.info(f"Enriched {perf_type}: {len(enriched_records)} records")
                    elif isinstance(perf_records, list):
                        self.logger.info(f"No {perf_type} data to enrich (empty list)")
                    else:
                        self.logger.warning(f"Unexpected {perf_type} data type: {type(perf_records)}")

                # Environmental data system information is now handled by dedicated enrichment processors
                # No need for post-enrichment fixes - EnvironmentalPowerEnrichment and EnvironmentalTemperatureEnrichment
                # handle system metadata injection and sensor type classification directly


                self.logger.info(f"Enriched performance data successfully - {len(enriched_data)} performance types processed")

            # Event enrichment is handled by the enrichment_processor.event_enricher
            # No need for a separate EventEnrichment instance

            # Configure Grafana integration if environment variables are available
            if enrichment_processor and enrichment_processor.event_enricher:
                grafana_url = os.environ.get('GRAFANA_API_URL')
                grafana_token = os.environ.get('GRAFANA_API_TOKEN')
                if grafana_url and grafana_token:
                    enrichment_processor.event_enricher.grafana_api_url = grafana_url
                    enrichment_processor.event_enricher.grafana_api_token = grafana_token
                    enrichment_processor.event_enricher.enable_grafana_annotations = True
                    self.logger.info("Grafana annotations enabled for event enrichment")

            # Extract event data and process through deduplication (from app/main.py lines 1750-1820)
            if CollectionType.EVENTS in collection_results:
                event_result = collection_results[CollectionType.EVENTS]
                if event_result.success and event_result.data:
                    event_data = event_result.data
                    self.logger.info("Event data extracted: %d event types", len(event_data))

            # Initialize writer (from app/main.py lines 1140-1155)
            from ..writer.factory import WriterFactory

            # Create writer if not already created and output format requires it
            if not self.writer and self.config.output != 'none':
                # Use pre-configured WriterConfig if available, otherwise create minimal one
                if self.writer_config:
                    writer_config = self.writer_config
                else:
                    # Create minimal WriterConfig (fallback - should not happen with new initialization flow)
                    writer_config = WriterConfig(
                        output_format=self.config.output,
                        system_id=sys_info.wwn if sys_info else 'unknown',
                        system_name=sys_info.name if sys_info else 'unknown'
                    )

                self.writer = WriterFactory.create_writer_from_config(writer_config)

            # Prepare writer data using centralized endpoint mapping
            writer_data = {}

            # Helper function to get proper measurement name using centralized config
            def get_measurement_name(data_type: str) -> str:
                """Get proper measurement name using centralized endpoint categorization."""
                # Import centralized system
                from collector.config.endpoint_categories import get_measurement_name as get_centralized_name

                # Use centralized system for all measurements
                return get_centralized_name(data_type)

            if enriched_data:
                for perf_type, perf_records in enriched_data.items():
                    if isinstance(perf_records, list) and len(perf_records) > 0:
                        # Use centralized mapping to get correct measurement name
                        measurement_name = get_measurement_name(perf_type)
                        writer_data[measurement_name] = perf_records
                        self.logger.info(f"Adding {len(perf_records)} {measurement_name} records to write (transformed from {perf_type})")

                        # NOTE: Removed duplicate environmental data entry - writers should only see clean measurement names

            # Add config data if available
            if config_data:
                # Enrich config data with storage_system_name and valuable fields
                enriched_config_data = enrichment_processor.enrich_config_data(config_data, sys_info_dict)

                # Add each config type as a separate measurement using centralized categorization
                for config_type, config_items in enriched_config_data.items():
                    if config_items:  # Only add non-empty config data
                        # Check if config_type is already a measurement name (Live API format)
                        if config_type.startswith(('config_', 'events_', 'performance_', 'env_', 'snapshot_')):
                            # Already in measurement format, use directly
                            writer_data[config_type] = config_items
                            self.logger.debug(f"Using config data directly: {config_type}")
                            continue

                        # Use centralized endpoint categorization to determine routing
                        # Clean up config_type to get the base endpoint name
                        endpoint_name = config_type.lower()

                        # Handle Live API format: 'config_storage_pools' -> 'storage_pools'
                        if endpoint_name.startswith('config_'):
                            endpoint_name = endpoint_name[7:]  # Remove 'config_' prefix

                        # Handle JSON replay format: 'VolumeConfig' -> 'volumes_config'
                        elif endpoint_name.endswith('config'):
                            # Convert camelCase to snake_case with _config suffix
                            base_name = endpoint_name[:-6]  # Remove 'config' suffix

                            # Handle special case mappings for JSON replay format
                            if base_name == 'volume':
                                endpoint_name = 'volumes_config'
                            elif base_name == 'interface':
                                endpoint_name = 'interfaces_config'
                            elif base_name == 'volumemappings':
                                endpoint_name = 'volume_mappings_config'
                            elif base_name == 'storagepool':
                                endpoint_name = 'storage_pools'
                            elif base_name == 'ethernet':
                                endpoint_name = 'ethernet_interface_config'
                            elif base_name == 'host':
                                endpoint_name = 'hosts'  # HostConfig -> hosts
                            elif base_name == 'hostgroups':
                                endpoint_name = 'host_groups'  # HostGroupsConfig -> host_groups
                            else:
                                # Generic conversion: add _config suffix
                                endpoint_name = f"{base_name}_config"

                        # Handle other legacy patterns
                        else:
                            endpoint_name = endpoint_name.replace('config', '').replace('statusconfig', '_status')
                            endpoint_name = endpoint_name.lstrip('_')

                        try:
                            category = get_endpoint_category(endpoint_name)
                            if category == EndpointCategory.EVENTS:
                                # Route to events using centralized mapping
                                events_measurement = get_measurement_name(endpoint_name)
                                writer_data[events_measurement] = config_items
                                self.logger.info(f"Routed {config_type} to events as {events_measurement}")
                            else:
                                # Route to config using centralized mapping
                                config_measurement = get_measurement_name(endpoint_name)
                                writer_data[config_measurement] = config_items
                                self.logger.info(f"Routed {config_type} to config as {config_measurement}")
                        except ValueError:
                            # Fallback for uncategorized endpoints - use legacy pattern
                            fallback_measurement = f"config_{config_type.lower()}"
                            writer_data[fallback_measurement] = config_items
                            self.logger.debug(f"Using fallback routing for uncategorized config: {config_type} -> {fallback_measurement}")

            # Process event data with deduplication
            if event_data:
                processed_events = []
                events_to_process = None

                # Extract events from the event_data structure - handle both dict and direct list
                if isinstance(event_data, dict):
                    if "events" in event_data and event_data["events"]:
                        events_to_process = event_data["events"]
                    elif "active_events" in event_data and event_data["active_events"]:
                        events_to_process = event_data["active_events"]
                    else:
                        # Direct dict structure with event types as keys (JSON replay format)
                        events_to_process = event_data
                        self.logger.info(f"Using JSON replay event structure with keys: {list(event_data.keys())}")
                elif isinstance(event_data, list):
                    # Direct list of events
                    events_to_process = {"events": event_data}

                if events_to_process and isinstance(events_to_process, dict):
                    # Process each event type through deduplication
                    total_events_before = 0
                    total_events_after = 0

                    for endpoint_name, event_list in events_to_process.items():
                        if isinstance(event_list, list) and event_list:
                            # Skip volume expansion progress events
                            if "volume_expansion_progress" in endpoint_name.lower():
                                self.logger.info(f"Event {endpoint_name}: {len(event_list)} -> 0 (skipped - mostly inactive data)")
                                continue

                            total_events_before += len(event_list)

                            # Apply full event enrichment (deduplication + system info) using processor
                            if enrichment_processor and enrichment_processor.event_enricher:
                                enriched_events = enrichment_processor.enrich_event_data(
                                    event_list, sys_info_dict, endpoint_name=endpoint_name
                                )
                                self.logger.info(f"Events processed with full enrichment for {endpoint_name}")

                                # Add enriched events to writer data
                                measurement_name = self._get_event_measurement_name(endpoint_name)
                                writer_data[measurement_name] = enriched_events
                                self.logger.info(f"Routed {endpoint_name} to {measurement_name} with enrichment")
                            else:
                                # Fallback to basic system info injection if processor not available
                                enriched_events = event_list
                                for event in enriched_events:
                                    if isinstance(event, dict):
                                        event.update(sys_info_dict)
                                self.logger.warning(f"Using basic event enrichment for {endpoint_name} - processor not available")

                                # Use centralized endpoint routing instead of hardcoded mappings
                                measurement_name = self._get_event_measurement_name(endpoint_name)
                                writer_data[measurement_name] = enriched_events
                                self.logger.info(f"Routed {endpoint_name} to {measurement_name} using centralized mapping")

                            # NOTE: Removed duplicate raw endpoint name entry - writers should only see clean measurement names
                            if enriched_events:
                                processed_events.extend(enriched_events)
                                total_events_after += len(enriched_events)
                                self.logger.info(f"Event {endpoint_name}: {len(event_list)} -> {len(enriched_events)} (after dedup)")
                            else:
                                self.logger.info(f"Event {endpoint_name}: {len(event_list)} -> 0 (duplicate/filtered)")

                    if processed_events:
                        self.logger.info(f"Processed {len(processed_events)} total events (filtered from {total_events_before} total)")
                    else:
                        self.logger.info(f"No events to write after deduplication (filtered {total_events_before} duplicates)")

            # Write data if any available
            if writer_data:
                # EARLY TRANSFORMATION: Ensure all keys are clean measurement names
                # This guarantees writers only receive standardized <category>_<object> names
                transformed_writer_data = {}
                for key, value in writer_data.items():
                    clean_measurement_name = get_measurement_name(key)
                    if clean_measurement_name != key:
                        self.logger.info(f"Early transformation: {key} → {clean_measurement_name}")

                    # Avoid duplicate keys by using the first occurrence
                    if clean_measurement_name not in transformed_writer_data:
                        transformed_writer_data[clean_measurement_name] = value
                    else:
                        self.logger.warning(f"Duplicate measurement name {clean_measurement_name} - merging data")
                        # If both are lists, merge them
                        if isinstance(transformed_writer_data[clean_measurement_name], list) and isinstance(value, list):
                            transformed_writer_data[clean_measurement_name].extend(value)
                        else:
                            # Keep the first occurrence
                            pass

                writer_data = transformed_writer_data
                self.logger.info(f"Early transformation complete: {len(writer_data)} clean measurement names for writers")

                # Convert data to serializable format (from app/main.py convert_to_serializable)
                def convert_to_serializable(obj, depth=0, max_depth=10):
                    """Recursively convert objects to JSON-serializable format."""
                    if depth > max_depth:
                        return f"<MAX_DEPTH_REACHED:{type(obj).__name__}>"

                    if obj is None:
                        return None

                    if isinstance(obj, (str, int, float, bool)):
                        return obj

                    # Enhanced BaseModel detection
                    is_basemodel = False
                    try:
                        if (hasattr(obj, 'model_dump') or
                            hasattr(obj, 'model_fields') or
                            'BaseModel' in str(type(obj).__bases__)):
                            is_basemodel = True
                    except Exception:
                        pass

                    if is_basemodel:
                        # Try multiple serialization methods
                        if hasattr(obj, 'model_dump'):
                            try:
                                return convert_to_serializable(obj.model_dump(), depth + 1, max_depth)
                            except Exception:
                                pass
                        if hasattr(obj, 'dict'):
                            try:
                                return convert_to_serializable(obj.dict(), depth + 1, max_depth)
                            except Exception:
                                pass
                        if hasattr(obj, '__dict__'):
                            try:
                                return convert_to_serializable(obj.__dict__, depth + 1, max_depth)
                            except Exception:
                                pass
                        return f"<BaseModel:{type(obj).__name__}:{str(obj)[:100]}>"

                    elif isinstance(obj, dict):
                        return {key: convert_to_serializable(value, depth + 1, max_depth) for key, value in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_to_serializable(item, depth + 1, max_depth) for item in obj]
                    elif hasattr(obj, 'isoformat'):
                        return obj.isoformat()
                    elif hasattr(obj, '__dict__') and not isinstance(obj, type):
                        return convert_to_serializable(obj.__dict__, depth + 1, max_depth)
                    else:
                        return str(obj)

                # Convert all writer data to serializable format
                serializable_data = {}
                for key, value in writer_data.items():
                    try:
                        self.logger.info(f"Converting {key} data: {len(value) if hasattr(value, '__len__') else 1} items")
                        serializable_data[key] = convert_to_serializable(value)
                        self.logger.info(f"Successfully converted {key} to serializable format")
                    except Exception as conv_e:
                        self.logger.error(f"Failed to convert {key}: {conv_e}")
                        serializable_data[key] = []

                # Write data
                # Write data if writer is available
                if self.writer:
                    success = self.writer.write(serializable_data, self.collections_completed + 1)
                else:
                    self.logger.warning("No writer available - skipping data write")
                    success = False
                if success:
                    self.logger.info("Data successfully written to output destination")
                    return True
                else:
                    self.logger.error("Failed to write data to output destination")
                    return False
            else:
                self.logger.info("No data to write")
                return True

        except Exception as e:
            self.logger.error(f"Failed to process and write data: {e}")
            import traceback
            self.logger.debug(f"Process and write traceback: {traceback.format_exc()}")
            return False

    def run_single_collection(self) -> bool:
        """Run a single collection cycle.

        Returns:
            True if collection cycle successful, False otherwise
        """
        start_time = time.time()

        try:
            # Collect all data types
            collection_results = self.collect_all_data()

            # Process and write the collected data
            success = self.process_and_write_data(collection_results)

            # Update statistics
            self.collections_completed += 1
            self.last_collection_time = time.time()

            duration = self.last_collection_time - start_time
            self.logger.info(f"Collection cycle {self.collections_completed} completed in {duration:.2f}s")

            return success

        except Exception as e:
            self.logger.error(f"Collection cycle failed: {e}")
            return False

    def run_continuous(self) -> None:
        """Run continuous collection loop.

        For JSON replay mode: processes all batches then exits
        For live API mode: runs indefinitely with configured interval
        Supports max_iterations for graceful exit after N iterations.
        """
        iteration_count = 0
        self.logger.info(f"Starting continuous collection (interval: {self.config.interval_time}s, max_iterations: {self.config.max_iterations if self.config.max_iterations > 0 else 'unlimited'})")

        try:
            if self.config.use_json_replay:
                # JSON replay mode: process all batches
                batch_count = 0
                while True:
                    batch_count += 1
                    iteration_count += 1

                    # Check max iterations
                    if self.config.max_iterations > 0 and iteration_count > self.config.max_iterations:
                        self.logger.info(f"Reached maximum iterations ({self.config.max_iterations}) - exiting")
                        break

                    self.logger.info(f"Processing JSON batch {batch_count}, iteration {iteration_count}")

                    success = self.run_single_collection()
                    if not success:
                        self.logger.warning(f"Batch {batch_count} collection failed")

                    self.collections_completed = iteration_count

                    # Try to advance to next batch
                    if self.datasource and hasattr(self.datasource, 'advance_batch'):
                        if not self.datasource.advance_batch():
                            self.logger.info(f"No more JSON batches. Processed {batch_count} batches total.")
                            break
                    else:
                        self.logger.info("No batch advancement available")
                        break

            else:
                # Live API mode: continuous collection
                while True:
                    iteration_count += 1

                    # Check max iterations
                    if self.config.max_iterations > 0 and iteration_count > self.config.max_iterations:
                        self.logger.info(f"Reached maximum iterations ({self.config.max_iterations}) - exiting")
                        break

                    self.logger.info(f"Starting collection iteration {iteration_count} of {self.config.max_iterations if self.config.max_iterations > 0 else 'unlimited'}")

                    success = self.run_single_collection()
                    if not success:
                        self.logger.warning("Collection cycle failed, continuing...")

                    self.collections_completed = iteration_count

                    # Wait for next collection (unless this was the final iteration)
                    if self.config.max_iterations == 0 or iteration_count < self.config.max_iterations:
                        self.logger.info(f"Waiting {self.config.interval_time} seconds until next collection...")
                        time.sleep(self.config.interval_time)
                    else:
                        self.logger.info(f"Completed final iteration {iteration_count} - not waiting for interval")

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
        except Exception as e:
            self.logger.error(f"Collection loop error: {e}")
        finally:
            self.cleanup()

    def _get_event_measurement_name(self, endpoint_name: str) -> str:
        """Get the proper measurement name for an event endpoint using centralized mapping.

        Args:
            endpoint_name: Original endpoint name from event data

        Returns:
            Standardized measurement name for writers
        """
        # Import centralized naming system
        from collector.config.endpoint_categories import get_measurement_name

        # Use centralized endpoint-to-measurement mapping
        standardized_name = get_measurement_name(endpoint_name)

        # Handle special cases for legacy JSON replay naming
        if standardized_name == endpoint_name and endpoint_name.startswith('events_'):
            # For events_ prefixed names that aren't in our mapping, they're already in measurement format
            return endpoint_name

        return standardized_name

    def _enrich_environmental_data(self, env_type: str, records: List[Dict[str, Any]], enrichment_processor) -> List[Dict[str, Any]]:
        """
        Enrich environmental data with system metadata and sensor classification.

        Args:
            env_type: Type of environmental data (env_power, env_temperature)
            records: List of environmental records to enrich
            enrichment_processor: The enrichment processor with environmental enrichers

        Returns:
            List of enriched environmental records
        """
        if not records:
            return records

        try:
            if env_type == 'env_power':
                return enrichment_processor.environmental_power_enricher.enrich_power_data(records)
            elif env_type == 'env_temperature':
                return enrichment_processor.environmental_temperature_enricher.enrich(records)
            else:
                self.logger.warning(f"Unknown environmental data type: {env_type}")
                return records

        except Exception as e:
            self.logger.error(f"Environmental enrichment failed for {env_type}: {e}")
            # Return original records on error to avoid data loss
            return records

    def cleanup(self) -> None:
        """Clean up collector resources with graceful writer shutdown."""
        # First ensure writer is properly closed and flushed (from app/main.py finally block)
        if self.writer:
            if hasattr(self.writer, 'close') and callable(getattr(self.writer, 'close')):
                self.logger.info("Collection finished - closing writer and flushing remaining data...")
                try:
                    self.writer.close(timeout_seconds=90, force_exit_on_timeout=False)
                    self.logger.info("Writer closed successfully")
                except Exception as e:
                    self.logger.warning(f"Error closing writer: {e}")
            self.writer = None

        # Clean up datasource
        if self.datasource:
            self.datasource.cleanup()

        self.logger.info("Collector cleanup completed")

    def get_statistics(self) -> Dict[str, Any]:
        """Get collection statistics.

        Returns:
            Dictionary with collection statistics
        """
        return {
            'collections_completed': self.collections_completed,
            'last_collection_time': self.last_collection_time,
            'datasource_type': 'json_replay' if self.config.use_json_replay else 'live_api',
            'system_info': self.datasource.get_system_info() if self.datasource else None
        }

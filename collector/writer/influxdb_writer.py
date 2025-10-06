"""
InfluxDB writer for E-Series Performance Analyzer.
Writes enriched performance data to InfluxDB 3.x with proper field type handling.

Note: this file leverages batching_example.py from the https://github.com/InfluxCommunity/influxdb3-python project
License: Apache License, Version 2.0, January 2004 (http://www.apache.org/licenses/)
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from influxdb_client_3 import InfluxDBClient3, WritePrecision, WriteOptions, write_client_options
from influxdb_client_3.exceptions.exceptions import InfluxDBError
from .base import Writer
from ..schema.base_model import BaseModel
from ..config.endpoint_categories import (
    get_endpoint_category, EndpointCategory, get_collection_behavior
)
from ..schema.models import (
    AnalysedDriveStatistics, AnalysedSystemStatistics,
    AnalysedInterfaceStatistics, AnalyzedControllerStatistics,
    DriveConfig, VolumeConfig, ControllerConfig, StoragePoolConfig,
    InterfaceConfig, HostConfig, HostGroupsConfig, SystemConfig,
    TrayConfig, VolumeMappingsConfig, EthernetConfig, SnapshotGroups,
    SnapshotSchedule, SnapshotImages
)
from ..validator.schema_validator import validate_measurements_for_influxdb, SchemaValidator
import inspect
from dataclasses import fields

LOG = logging.getLogger(__name__)

class BatchingCallback(object):
    """
    Callback handler for batched InfluxDB writes.

    Tracks write success/failure statistics and provides timing information
    for performance monitoring and debugging.
    """

    def __init__(self):
        self.write_status_msg = None
        self.write_count = 0
        self.error_count = 0
        self.retry_count = 0
        self.start = time.time_ns()

    def success(self, conf, data: str):
        """Called when a batch write succeeds."""
        self.write_count += 1
        self.write_status_msg = f"SUCCESS: {self.write_count} batches written"
        LOG.debug(f"Batch write successful: {len(data)} bytes")

    def error(self, conf, data: str, exception: InfluxDBError):
        """Called when a batch write fails permanently."""
        self.error_count += 1
        self.write_status_msg = f"FAILURE: {exception}"
        LOG.error(f"Batch write failed: {len(data)} bytes, error: {exception}")

    def retry(self, conf, data: str, exception: InfluxDBError):
        """Called when a batch write fails but will be retried."""
        self.retry_count += 1
        LOG.warning(f"Batch write retry {self.retry_count}: {len(data)} bytes, error: {exception}")

    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        return (time.time_ns() - self.start) // 1_000_000

    def get_stats(self) -> Dict[str, Any]:
        """Get write statistics."""
        return {
            'writes': self.write_count,
            'errors': self.error_count,
            'retries': self.retry_count,
            'elapsed_ms': self.elapsed_ms(),
            'status': self.write_status_msg
        }

class InfluxDBWriter(Writer):
    """
    Writer implementation for InfluxDB 3.x.

    Handles:
    - Second-level timestamp precision (no nanosecond bloat)
    - Automatic field type conversion using BaseModel mixin
    - observedTimeInMS conversion to seconds since epoch
    - Enriched tag and field mapping
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize InfluxDB writer with configuration."""

        # Extract InfluxDB connection parameters from environment variables or config
        import os
        self.url = config.get('influxdb_url') or os.getenv('INFLUXDB_URL', 'https://influxdb:8181')
        self.token = config.get('influxdb_token') or os.getenv('INFLUXDB_TOKEN', '')
        self.database = config.get('influxdb_database') or os.getenv('INFLUXDB_DATABASE', 'epa')
        # self.org = config.get('influxdb_org') or os.getenv('INFLUXDB_ORG', 'netapp')
        self.tls_ca = config.get('tls_ca', None)
        # Get TLS validation setting from config (passed from main.py)
        self.tls_validation = config.get('tls_validation', 'strict')
        # Store system identification for environmental data
        self.system_id = config.get('system_id')
        self.system_name = config.get('system_name')
        LOG.info(f"InfluxDBWriter initialized with system_id: {self.system_id}")

        self.batch_size = 500  # Target batch size
        self.flush_interval = 60_000  # 60 seconds - matches collection interval
        LOG.info("Multi-iteration mode: using throughput batching (batch_size=500, flush_interval=60s)")

        self.batch_callback = BatchingCallback()  # Initialize callback for batching statistics

        # Initialize client
        self.client = None
        self._initialize_client()

        # Initialize schema validator for model-based type conversion
        self.schema_validator = SchemaValidator()

        # Enable debug file output based on factory-provided directory
        self.debug_output_dir = config.get('json_output_dir')
        self.enable_debug_output = self.debug_output_dir is not None

        if self.enable_debug_output:
            LOG.info(f"InfluxDB debug file output enabled -> {self.debug_output_dir}")

        LOG.info(f"InfluxDBWriter initialized: {self.url} -> {self.database}")

    def _initialize_client(self):
        """Initialize the InfluxDB client with proper TLS configuration."""
        try:
            # InfluxDB always requires strict TLS validation - ignore user's tls_validation setting
            if self.tls_validation == 'disable' or self.tls_validation == 'none':
                LOG.warning("TLS validation 'disable'/'none' not supported for InfluxDB - InfluxDB requires strict TLS validation")

            # Configure write options for efficient batching (following official example)
            write_options = WriteOptions(
                batch_size=self.batch_size,         # Dynamic batch size based on MAX_ITERATIONS
                flush_interval=self.flush_interval, # Dynamic flush interval for immediate vs throughput mode
                jitter_interval=2_000,       # 2 seconds
                retry_interval=5_000,        # 5 seconds
                max_retries=2,
                max_retry_delay=15_000,      # 15 seconds
                max_close_wait=60_000,       # 60 seconds - reasonable timeout for container shutdowns
                exponential_base=2
            )

            # Configure write client options with callbacks (following official example)
            wco = write_client_options(
                success_callback=self.batch_callback.success,
                error_callback=self.batch_callback.error,
                retry_callback=self.batch_callback.retry,
                write_options=write_options
            )

            # Always use strict TLS validation for InfluxDB
            client_kwargs = {
                'host': self.url,
                'database': self.database,
                'token': self.token,
                'enable_gzip': True,  # Enable gzip compression for better performance
                'write_client_options': wco,  # Batching configuration
                'verify_ssl': True,  # InfluxDB always uses strict TLS validation
                'timeout': 60000  # 60 second timeout (in milliseconds)
            }

            # Check for custom CA certificate from environment or config
            ca_cert_path = self.tls_ca or os.getenv('INFLUXDB3_TLS_CA')
            if ca_cert_path and os.path.exists(ca_cert_path):
                LOG.info(f"Using custom CA certificate: {ca_cert_path}")
                client_kwargs['ssl_ca_cert'] = ca_cert_path
            elif ca_cert_path:
                LOG.warning(f"CA certificate path specified but file not found: {ca_cert_path}")
            elif not ca_cert_path:
                # No TLS CA specified - warn user since InfluxDB uses strict validation
                LOG.warning("No TLS CA certificate specified (--tlsCa or TLS_CA environment variable). "
                           "InfluxDB requires strict TLS validation - falling back to system truststore. "
                           "If using self-signed certificates, this connection will fail.")

            self.client = InfluxDBClient3(**client_kwargs)
            LOG.info(f"InfluxDB client created successfully with strict TLS validation to {self.url}")

            # Ensure database exists (with proper TLS handling)
            self._ensure_database_exists()

        except Exception as e:
            LOG.error(f"Failed to create InfluxDB client: {e}")
            raise

    def _ensure_database_exists(self):
        """Ensure the target database exists, creating it if necessary."""
        try:
            import requests

            headers = {
                'Authorization': f'Bearer {self.token}',
                'Accept': 'application/json'
            }

            # Determine TLS verification - use custom CA if available, otherwise strict validation
            ca_cert_path = self.tls_ca or os.getenv('INFLUXDB3_TLS_CA')
            verify_tls = ca_cert_path if ca_cert_path and os.path.exists(ca_cert_path) else True

            # GET existing databases - always use strict TLS validation for InfluxDB
            get_url = f"{self.url}/api/v3/configure/database?format=json"
            response = requests.get(get_url, headers=headers, timeout=10, verify=verify_tls)

            if response.status_code == 200:
                databases_data = response.json()
                LOG.debug(f"Database list response type: {type(databases_data)}, content: {databases_data}")

                # Handle multiple response formats from InfluxDB database API
                databases = []
                if isinstance(databases_data, list):
                    # Check if it's a list of database name objects: [{"iox::database": "name"}]
                    if databases_data and isinstance(databases_data[0], dict) and "iox::database" in databases_data[0]:
                        databases = [db_obj["iox::database"] for db_obj in databases_data]
                        LOG.debug(f"API returned database object list: {databases}")
                    else:
                        # Simple list of database names: ["_internal", "epa"]
                        databases = databases_data
                        LOG.debug(f"API returned database name list: {databases}")
                elif isinstance(databases_data, dict):
                    databases = databases_data.get('databases', [])
                    LOG.debug(f"API returned database dict, extracted list: {databases}")
                else:
                    LOG.warning(f"Unexpected database list response format: {type(databases_data)}")
                    databases = []

                if self.database not in databases:
                    LOG.info(f"Database '{self.database}' does not exist, creating it")

                    # POST to create database - use same TLS validation as GET request
                    create_url = f"{self.url}/api/v3/configure/database"
                    create_data = {"db": self.database}
                    create_response = requests.post(create_url, json=create_data, headers=headers, timeout=10, verify=verify_tls)

                    if create_response.status_code in [200, 201, 204]:
                        LOG.info(f"Successfully created database '{self.database}'")
                    else:
                        LOG.error(f"Failed to create database '{self.database}': HTTP {create_response.status_code}")
                        LOG.error(f"Response: {create_response.text}")
                else:
                    LOG.info(f"Database '{self.database}' already exists")
            else:
                LOG.warning(f"Failed to check database existence: HTTP {response.status_code}")
                LOG.warning(f"Response: {response.text}")

        except Exception as db_error:
            LOG.warning(f"Could not verify database existence (will be created on first write): {db_error}")

    def write(self, measurements: Dict[str, Any], loop_iteration: int = 1) -> bool:
        """
        Write measurement data to InfluxDB using automatic client-side batching.

        Args:
            measurements: Dictionary of measurement name -> measurement data
            loop_iteration: Current iteration number for debug file naming

        Returns:
            bool: True if all writes succeeded, False otherwise
        """
        # Apply schema-based validation before writing to InfluxDB
        LOG.debug("Applying schema validation to measurements")
        try:
            from ..validator.schema_validator import validate_measurements_for_influxdb
            measurements = validate_measurements_for_influxdb(measurements)
            LOG.debug("Schema validation completed successfully")
        except Exception as e:
            LOG.error(f"Schema validation failed: {e}")
            import traceback
            LOG.error(traceback.format_exc())

        if not self.client:
            LOG.error("InfluxDB client not available")
            return False

        success = True
        written_count = 0

        for measurement_name, measurement_data in measurements.items():
            try:
                if not measurement_data:
                    LOG.debug(f"No data for measurement: {measurement_name}")
                    continue

                LOG.info(f"Processing InfluxDB measurement: {measurement_name} (Batch size: {len(measurement_data) if hasattr(measurement_data, '__len__') else 1} records)")

                # Debug tray config specifically
                if 'trayconfig' in measurement_name:
                    LOG.info(f"TRAY DEBUG: Processing {measurement_name} with {len(measurement_data) if hasattr(measurement_data, '__len__') else 1} records")

                # Debug ethernet config specifically
                if 'ethernetconfig' in measurement_name:
                    LOG.info(f"ETHERNET DEBUG: Processing {measurement_name} with {len(measurement_data) if hasattr(measurement_data, '__len__') else 1} records")

                # Convert to InfluxDB Point objects
                points = self._convert_to_points(measurement_name, measurement_data)

                # Debug tray config point conversion
                if 'trayconfig' in measurement_name:
                    LOG.info(f"TRAY DEBUG: Converted to {len(points)} points for {measurement_name}")

                # Debug ethernet config point conversion
                if 'ethernetconfig' in measurement_name:
                    LOG.info(f"ETHERNET DEBUG: Converted to {len(points)} points for {measurement_name}")
                    if not points:
                        LOG.warning(f"ETHERNET DEBUG: No points created - check conversion process")

                if points:
                    # Write points using client's automatic batching (following official example)
                    # The client automatically batches writes based on write_options configuration
                    for point in points:
                        try:
                            self.client.write(record=point)
                            written_count += 1
                        except Exception as point_e:
                            LOG.error(f"Failed to write point: {point_e}")
                            success = False

                    LOG.info(f"Successfully submitted {len(points)} points for {measurement_name} (automatic batching enabled)")
                else:
                    LOG.warning(f"No valid points converted for measurement: {measurement_name}")

            except Exception as e:
                LOG.error(f"Failed to process InfluxDB measurement {measurement_name}: {e}", exc_info=True)
                success = False

        if written_count > 0:
            LOG.info(f"InfluxDB write submitted: {written_count} total points (batched by client)")

            # For single iteration mode, flush immediately to avoid delays during close()
            if os.getenv('MAX_ITERATIONS', '1') == '1':
                try:
                    LOG.info("Single iteration detected - flushing InfluxDB client immediately")
                    if (self.client and hasattr(self.client, '_client') and
                        hasattr(self.client._client, 'write_api')):
                        write_api = self.client._client.write_api()
                        if hasattr(write_api, 'flush'):
                            write_api.flush()
                            LOG.info("InfluxDB write_api flushed successfully")
                        else:
                            LOG.debug("No flush method available on write_api")
                    else:
                        LOG.debug("No write_api available for flushing")
                except Exception as e:
                    LOG.warning(f"Failed to flush InfluxDB client: {e}")

        # Write debug output files if enabled
        if self.enable_debug_output:
            self._write_debug_input_json(measurements, loop_iteration)
            self._write_debug_line_protocol(measurements, loop_iteration)

        return success

    def _convert_to_points(self, measurement_name: str, data: Any) -> List:
        """
        Convert measurement data to InfluxDB Point objects for automatic batching.

        Args:
            measurement_name: Name of the measurement
            data: Raw measurement data (list of dicts or dataclasses)

        Returns:
            List of InfluxDB Point objects
        """
        # First convert to line protocol format (existing logic)
        records = self._convert_to_line_protocol(measurement_name, data)

        # Then convert dictionaries to Point objects
        from influxdb_client_3 import Point
        points = []

        for record in records:
            try:
                # Create Point object
                point = Point(measurement_name)

                # Add tags
                tags = record.get('tags', {})
                for tag_key, tag_value in tags.items():
                    if tag_value is not None:
                        point = point.tag(tag_key, str(tag_value))

                # Add fields
                fields = record.get('fields', {})
                for field_key, field_value in fields.items():
                    if field_value is not None:
                        point = point.field(field_key, field_value)

                # Add timestamp
                timestamp = record.get('time')
                if timestamp:
                    point = point.time(timestamp, WritePrecision.S)

                points.append(point)

            except Exception as e:
                LOG.error(f"Failed to convert record to Point: {e}")
                continue

        LOG.debug(f"Converted {len(records)} records to {len(points)} Point objects for {measurement_name}")
        return points

    def _convert_to_line_protocol(self, measurement_name: str, data: Any) -> List[Dict[str, Any]]:
        """
        Convert measurement data to InfluxDB line protocol format.

        Args:
            measurement_name: Name of the measurement
            data: Raw measurement data (list of dicts or dataclasses)

        Returns:
            List of InfluxDB record dictionaries
        """
        LOG.debug(f"Converting {measurement_name} to line protocol (data_len={len(data) if hasattr(data, '__len__') else 1})")
        records = []

        # Ensure data is a list
        if not isinstance(data, list):
            data = [data] if data else []

        for item in data:
            try:
                # Convert dataclass to dict if needed
                if hasattr(item, '__dict__'):
                    item_dict = item.__dict__
                elif isinstance(item, dict):
                    item_dict = item
                else:
                    LOG.warning(f"Unexpected data type for InfluxDB: {type(item)}")
                    continue

                # Use centralized conversion method routing instead of hardcoded if/elif chain
                conversion_method = self._get_conversion_method(measurement_name)

                if conversion_method:
                    record = conversion_method(measurement_name, item_dict)
                else:
                    LOG.warning(f"No conversion method found for measurement: {measurement_name}")
                    record = self._convert_generic_record(measurement_name, item_dict)

                if record:
                    records.append(record)

            except Exception as e:
                LOG.warning(f"Failed to convert record in {measurement_name}: {e}")
                continue

        return records

    def _check_system_identification_tags(self, tags: Dict[str, str], measurement_name: str = "unknown") -> None:
        """
        Check system identification tags and log warning if they are unknown.

        This indicates that enrichment may have failed to properly identify the storage system.

        Args:
            tags: Dictionary of tag key-value pairs
            measurement_name: Name of the measurement for context in warning message
        """
        system_name = tags.get('storage_system_name', '')
        system_wwn = tags.get('storage_system_wwn', '')

        # Only warn if both are unknown - partial identification is acceptable
        if system_name == 'unknown' and system_wwn == 'unknown':
            LOG.warning(f"{measurement_name} record has unknown system identification: name='{system_name}', wwn='{system_wwn}' - enrichment may have failed")

    def _write_debug_line_protocol(self, measurements: Dict[str, Any], loop_iteration: int = 1):
        """
        Write generated line protocol to text file for debugging/validation.
        Only enabled when COLLECTOR_LOG_LEVEL=DEBUG.
        """
        if not self.enable_debug_output:
            return

        try:
            import os
            from datetime import datetime

            # Ensure output directory exists
            os.makedirs(self.debug_output_dir, exist_ok=True)

            # Use iteration-based filename to preserve iteration 1's config data
            if loop_iteration == 1:
                filename = "iteration_1_influxdb_line_protocol_final.txt"
            else:
                filename = "influxdb_line_protocol_final.txt"
            filepath = os.path.join(self.debug_output_dir, filename)

            # Generate line protocol for all measurements
            line_protocol_lines = []

            for measurement_name, measurement_data in measurements.items():
                if not measurement_data:
                    continue

                # Convert to line protocol format (reuse existing logic)
                records = self._convert_to_line_protocol(measurement_name, measurement_data)

                for record in records:
                    try:
                        # Convert record dict to InfluxDB line protocol format
                        line = self._record_to_line_protocol(record)
                        if line:
                            line_protocol_lines.append(line)
                    except Exception as e:
                        LOG.debug(f"Failed to convert record to line protocol: {e}")
                        continue

            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                for line in line_protocol_lines:
                    f.write(line + '\n')

            LOG.info(f"InfluxDB line protocol debug output saved to: {filepath} ({len(line_protocol_lines)} lines)")

        except Exception as e:
            LOG.error(f"Failed to write InfluxDB debug line protocol: {e}")

    def _convert_to_points(self, measurement_name: str, data: Any) -> List:
        """
        Convert measurement data to InfluxDB Point objects for automatic batching.

        Args:
            measurement_name: Name of the measurement
            data: Raw measurement data (list of dicts or dataclasses)

        Returns:
            List of InfluxDB Point objects
        """
        # First convert to line protocol format (existing logic)
        records = self._convert_to_line_protocol(measurement_name, data)

        # Then convert dictionaries to Point objects
        from influxdb_client_3 import Point
        points = []

        for record in records:
            try:
                # Create Point object
                point = Point(measurement_name)

                # Add tags
                tags = record.get('tags', {})
                for tag_key, tag_value in tags.items():
                    if tag_value is not None:
                        point = point.tag(tag_key, str(tag_value))

                # Add fields
                fields = record.get('fields', {})
                for field_key, field_value in fields.items():
                    if field_value is not None:
                        point = point.field(field_key, field_value)

                # Add timestamp
                timestamp = record.get('time')
                if timestamp:
                    point = point.time(timestamp, WritePrecision.S)

                points.append(point)

            except Exception as e:
                LOG.error(f"Failed to convert record to Point: {e}")
                continue

        LOG.debug(f"Converted {len(records)} records to {len(points)} Point objects for {measurement_name}")

        # Debug tray config point creation
        if 'trayconfig' in measurement_name:
            LOG.info(f"TRAY POINT DEBUG: {measurement_name} - {len(records)} records -> {len(points)} points")
            if points and len(points) > 0:
                sample_point = points[0]
                LOG.info(f"TRAY POINT DEBUG: Sample point: {sample_point}")
            else:
                LOG.warning(f"TRAY POINT DEBUG: No points created for {measurement_name}!")

        # Debug ethernet config point creation
        if 'ethernetconfig' in measurement_name:
            LOG.info(f"ETHERNET POINT DEBUG: {measurement_name} - {len(records)} records -> {len(points)} points")
            if points and len(points) > 0:
                sample_point = points[0]
                LOG.info(f"ETHERNET POINT DEBUG: Sample point created successfully")
                try:
                    # Try to examine the point structure
                    LOG.info(f"ETHERNET POINT DEBUG: Point type: {type(sample_point)}")
                except Exception as e:
                    LOG.warning(f"ETHERNET POINT DEBUG: Error examining point: {e}")
            else:
                LOG.warning(f"ETHERNET POINT DEBUG: No points created for {measurement_name}!")

        return points

    def _get_conversion_method(self, measurement_name: str):
        """
        Get the appropriate conversion method for a measurement using centralized categorization.
        This replaces the old hardcoded if/elif chain with centralized endpoint routing.

        Args:
            measurement_name: Name of the measurement to convert

        Returns:
            Conversion method function or None if no specific method found
        """
        # Handle config measurements (always start with config_)
        if measurement_name.startswith('config_'):
            return self._convert_config_record

        # Handle direct event measurements
        if measurement_name == 'events_system_failures':
            return self._convert_system_failures_record
        if measurement_name in ['events_lockdown_status', 'lockdown_status']:
            return lambda name, data: self._convert_lockdown_status_record(data)

        # Handle environmental measurements (special Symbol API format)
        if measurement_name in ['env_power', 'power']:
            return self._convert_environmental_power_record
        if measurement_name in ['env_temperature', 'temp']:
            return self._convert_environmental_temperature_record

        # Try centralized categorization for other measurements
        try:
            # Convert measurement name back to endpoint name for categorization
            from collector.config.endpoint_categories import get_endpoint_from_measurement
            endpoint_name = get_endpoint_from_measurement(measurement_name)
            category = get_endpoint_category(endpoint_name)

            # Map categories to conversion methods
            category_conversion_mapping = {
                EndpointCategory.PERFORMANCE: self._get_performance_conversion_method,
                EndpointCategory.EVENTS: self._get_event_conversion_method,
                EndpointCategory.CONFIGURATION: self._get_config_conversion_method
            }

            conversion_method = category_conversion_mapping.get(category)
            if conversion_method:
                # For performance measurements, need to determine specific type
                if category == EndpointCategory.PERFORMANCE:
                    return conversion_method(measurement_name)
                elif category == EndpointCategory.EVENTS:
                    return conversion_method(measurement_name)
                elif category == EndpointCategory.CONFIGURATION:
                    return conversion_method(measurement_name)
                else:
                    return conversion_method

        except ValueError:
            # Fallback to pattern matching for uncategorized measurements
            return self._get_fallback_conversion_method(measurement_name)

        return self._convert_generic_record

    def _get_performance_conversion_method(self, measurement_name: str):
        """Get specific conversion method for performance measurements."""
        if 'volume' in measurement_name.lower():
            return self._convert_volume_record
        elif 'drive' in measurement_name.lower():
            return self._convert_drive_record
        elif 'controller' in measurement_name.lower():
            return self._convert_controller_record
        elif 'interface' in measurement_name.lower():
            return self._convert_interface_record
        elif 'system' in measurement_name.lower():
            return self._convert_system_record
        else:
            return self._convert_generic_record

    def _get_event_conversion_method(self, measurement_name: str):
        """Get specific conversion method for event measurements."""
        if 'systemfailures' in measurement_name or 'system_failures' in measurement_name:
            return self._convert_system_failures_record
        elif 'lockdown' in measurement_name:
            return lambda name, data: self._convert_lockdown_status_record(data)
        else:
            return self._convert_generic_record

    def _get_config_conversion_method(self, measurement_name: str):
        """Get specific conversion method for configuration measurements using schema-based conversion."""
        if 'drive' in measurement_name.lower():
            return self._convert_drive_config_record
        elif 'volume' in measurement_name.lower():
            return self._convert_volume_config_record
        elif 'controller' in measurement_name.lower():
            return self._convert_controller_config_record
        elif 'storage_pool' in measurement_name.lower() or 'storagepool' in measurement_name.lower():
            return self._convert_storage_pool_config_record
        elif 'interface' in measurement_name.lower():
            return self._convert_interface_config_record
        elif 'host_group' in measurement_name.lower() or 'hostgroup' in measurement_name.lower():
            return self._convert_host_group_config_record
        elif 'host' in measurement_name.lower():
            return self._convert_host_config_record
        elif 'system' in measurement_name.lower():
            return self._convert_system_config_record
        elif 'tray' in measurement_name.lower():
            return self._convert_tray_config_record
        elif 'mapping' in measurement_name.lower():
            return self._convert_volume_mapping_config_record
        elif 'ethernet' in measurement_name.lower():
            return self._convert_ethernet_config_record
        elif 'snapshot' in measurement_name.lower():
            return self._convert_snapshot_config_record
        else:
            # Fallback to old method for unknown config types
            return self._convert_config_record

    def _get_fallback_conversion_method(self, measurement_name: str):
        """Fallback pattern matching for uncategorized measurements."""
        # This preserves the old logic for uncategorized measurements
        if 'volume' in measurement_name.lower():
            return self._convert_volume_record
        elif 'drive' in measurement_name.lower():
            return self._convert_drive_record
        elif 'controller' in measurement_name.lower():
            return self._convert_controller_record
        elif 'interface' in measurement_name.lower():
            return self._convert_interface_record
        elif 'system' in measurement_name.lower():
            return self._convert_system_record
        else:
            return self._convert_generic_record

    def _convert_to_line_protocol(self, measurement_name: str, data: Any) -> List[Dict[str, Any]]:
        """
        Convert measurement data to InfluxDB line protocol format.

        Args:
            measurement_name: Name of the measurement
            data: Raw measurement data (list of dicts or dataclasses)

        Returns:
            List of InfluxDB record dictionaries
        """
        LOG.debug(f"Converting {measurement_name} to line protocol (data_len={len(data) if hasattr(data, '__len__') else 1})")
        records = []

        # Ensure data is a list
        if not isinstance(data, list):
            data = [data] if data else []

        for item in data:
            try:
                # Convert dataclass to dict if needed
                if hasattr(item, '__dict__'):
                    item_dict = item.__dict__
                elif isinstance(item, dict):
                    item_dict = item
                else:
                    LOG.warning(f"Unexpected data type for InfluxDB: {type(item)}")
                    continue

                # Use centralized conversion method routing instead of hardcoded if/elif chain
                conversion_method = self._get_conversion_method(measurement_name)

                if conversion_method:
                    record = conversion_method(measurement_name, item_dict)
                else:
                    LOG.warning(f"No conversion method found for measurement: {measurement_name}")
                    record = self._convert_generic_record(measurement_name, item_dict)

                if record:
                    records.append(record)

            except Exception as e:
                LOG.warning(f"Failed to convert record in {measurement_name}: {e}")
                continue

        return records

    def _check_system_identification_tags(self, tags: Dict[str, str], measurement_name: str = "unknown") -> None:
        """
        Check system identification tags and log warning if they are unknown.

        This indicates that enrichment may have failed to properly identify the storage system.

        Args:
            tags: Dictionary of tag key-value pairs
            measurement_name: Name of the measurement for context in warning message
        """
        system_name = tags.get('storage_system_name', '')
        system_wwn = tags.get('storage_system_wwn', '')

        # Only warn if both are unknown - partial identification is acceptable
        if system_name == 'unknown' and system_wwn == 'unknown':
            LOG.warning(f"{measurement_name} record has unknown system identification: name='{system_name}', wwn='{system_wwn}' - enrichment may have failed")

    def _convert_volume_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert volume performance data to InfluxDB record format."""

        # Extract tags (indexed fields) - use both snake_case and camelCase
        # Sanitize tag values to avoid InfluxDB issues
        system_tags = self._get_standardized_system_tags(data)
        tags = {
            'volume_id': self._sanitize_tag_value(str(self._get_field_value(data, 'volume_id') or 'unknown')),
            'volume_name': self._sanitize_tag_value(str(self._get_field_value(data, 'volume_name') or 'unknown')),
            'controller_id': self._sanitize_tag_value(str(self._get_field_value(data, 'controller_id') or 'unknown')),
            'controller_unit': self._sanitize_tag_value(str(self._get_field_value(data, 'controller_unit') or 'unknown')),
            'host': self._sanitize_tag_value(str(data.get('host', 'unknown'))),
            'host_group': self._sanitize_tag_value(str(data.get('host_group', 'unknown'))),
            'storage_pool': self._sanitize_tag_value(str(data.get('storage_pool', 'unknown'))),
            **system_tags
        }

        # Check system identification tags and log warning if unknown
        self._check_system_identification_tags(tags, measurement_name)

        # Extract fields (values) using BaseModel conversion
        fields = {}

        # Performance metrics
        performance_fields = [
            'combined_iops', 'read_iops', 'other_iops',
            'combined_throughput', 'read_throughput', 'write_throughput',
            'combined_response_time', 'read_response_time', 'write_response_time',
            'average_queue_depth', 'queue_depth_max', 'queue_depth_total',
            'average_read_op_size', 'average_write_op_size',
            'read_cache_utilization', 'write_cache_utilization',
            'random_bytes_percent', 'random_ios_percent'
        ]

        for field_name in performance_fields:
            value = self._get_field_value(data, field_name)
            if value is not None:
                # Use value as-is from model - AnalysedVolumeStatistics defines these as Optional[float]
                fields[field_name] = value

        # Get timestamp - convert observedTimeInMS to seconds
        timestamp = self._extract_timestamp(data)

        if not fields:
            LOG.debug(f"No valid fields found for volume record: {tags['volume_name']}")
            return None

        return {
            'measurement': self.get_final_measurement_name(measurement_name),
            'tags': tags,
            'fields': fields,
            'time': timestamp
        }

    def _convert_drive_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert drive performance data to InfluxDB record format using schema."""
        return self._convert_schema_record(measurement_name, data, AnalysedDriveStatistics, {
            # Drive stats: use sourceController for controller_id (no controllerId field available)
            'controller_id': ('sourceController', 'unknown'),
            'drive_id': ('diskId', 'unknown'),
            'drive_slot': ('driveSlot', 'unknown'),
            'volume_group_id': ('volGroupId', 'unknown'),
            'volume_group_name': ('volGroupName', 'unknown'),
            'tray_id': ('trayId', 'unknown')
            # System identification comes from enrichment, not deprecated schema fields
        }, [
            'combined_iops', 'read_iops', 'write_iops', 'other_iops',
            'combined_throughput', 'read_throughput', 'write_throughput',
            'combined_response_time', 'read_response_time', 'write_response_time',
            'average_queue_depth', 'queue_depth_max', 'average_read_op_size', 'average_write_op_size',
            'read_physical_iops', 'write_physical_iops', 'read_time_max', 'write_time_max',
            'random_bytes_percent', 'random_ios_percent'
        ])

    def _convert_controller_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert controller performance data to InfluxDB record format using schema."""
        LOG.debug(f"_convert_controller_record: measurement_name={measurement_name}, data_type={type(data)}")
        LOG.debug(f"_convert_controller_record: data_keys={list(data.keys()) if isinstance(data, dict) else 'not_dict'}")

        # Controller statistics come wrapped in a "statistics" array
        if isinstance(data, dict) and 'statistics' in data:
            LOG.debug(f"_convert_controller_record: Found statistics array with {len(data['statistics'])} items")
            results = []
            for i, stat in enumerate(data['statistics']):
                LOG.debug(f"_convert_controller_record: Processing statistic {i+1}/{len(data['statistics'])}")
                record = self._convert_schema_record(measurement_name, stat, AnalyzedControllerStatistics, {
                    'controller_id': ('controllerId', 'unknown'),
                    'controller_unit': ('controller_unit', 'unknown'),  # Use enriched field name
                    # Controller stats: use sourceController for source_controller (controller collecting the data)
                    'source_controller': ('sourceController', 'unknown')
                    # System identification handled by _get_standardized_system_tags()
                }, [
                    'combined_iops', 'read_iops', 'write_iops', 'other_iops',
                    'combined_throughput', 'read_throughput', 'write_throughput',
                    'combined_response_time', 'read_response_time', 'write_response_time',
                    'average_read_op_size', 'average_write_op_size', 'read_physical_iops', 'write_physical_iops',
                    'cache_hit_bytes_percent', 'random_ios_percent', 'mirror_bytes_percent',
                    'full_stripe_writes_bytes_percent', 'max_cpu_utilization', 'cpu_avg_utilization'
                ])
                if record:
                    LOG.debug(f"_convert_controller_record: Successfully converted statistic {i+1}")
                    results.append(record)
                else:
                    LOG.warning(f"_convert_controller_record: Failed to convert statistic {i+1}")
            LOG.debug(f"_convert_controller_record: Returning {len(results)} records from statistics array")
            return results[0] if results else None
        else:
            LOG.debug(f"_convert_controller_record: No statistics array found, processing as single record")
            return self._convert_schema_record(measurement_name, data, AnalyzedControllerStatistics, {
                'controller_id': ('controllerId', 'unknown'),
                'controller_unit': ('controller_unit', 'unknown'),  # Use enriched field name
                # Controller stats: use sourceController for source_controller (controller collecting the data)
                'source_controller': ('sourceController', 'unknown')
                # System identification handled by _get_standardized_system_tags()
            }, [
                'combined_iops', 'read_iops', 'write_iops', 'other_iops',
                'combined_throughput', 'read_throughput', 'write_throughput',
                'combined_response_time', 'read_response_time', 'write_response_time',
                'average_read_op_size', 'average_write_op_size', 'read_physical_iops', 'write_physical_iops',
                'cache_hit_bytes_percent', 'random_ios_percent', 'mirror_bytes_percent',
                'full_stripe_writes_bytes_percent', 'max_cpu_utilization', 'cpu_avg_utilization'
            ])

    def _convert_interface_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert interface performance data to InfluxDB record format using schema."""
        return self._convert_schema_record(measurement_name, data, AnalysedInterfaceStatistics, {
            'interface_id': ('interfaceId', 'unknown'),
            'controller_id': ('controller_id', 'unknown'),  # Use enriched field name
            'controller_unit': ('controller_unit', 'unknown'),  # Use enriched field name
            'channel_type': ('channelType', 'unknown'),
            'channel_number': ('channelNumber', 'unknown'),
            'storage_system_name': ('system_name', 'unknown'),  # Use enriched field name
            'storage_system_wwn': ('system_wwn', 'unknown')     # Use enriched field name
        }, [
            'combined_iops', 'read_iops', 'write_iops', 'other_iops',
            'combined_throughput', 'read_throughput', 'write_throughput',
            'combined_response_time', 'read_response_time', 'write_response_time',
            'average_read_op_size', 'average_write_op_size', 'queue_depth_total', 'queue_depth_max',
            'channel_error_counts'
        ])

    def _convert_system_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert system performance data to InfluxDB record format using schema."""
        return self._convert_schema_record(measurement_name, data, AnalysedSystemStatistics, {
            # System stats: use sourceController for source_controller (controller collecting the data)
            'source_controller': ('sourceController', 'unknown'),
            # System identification comes from enrichment, not deprecated schema fields
            'name': ('system_name', 'unknown'),  # Use enriched field name
            'wwn': ('system_wwn', 'unknown')     # Use enriched field name
        }, [
            'combined_iops', 'read_iops', 'write_iops', 'other_iops',
            'combined_throughput', 'read_throughput', 'write_throughput',
            'combined_response_time', 'read_response_time', 'write_response_time',
            'average_read_op_size', 'average_write_op_size', 'read_physical_iops', 'write_physical_iops',
            'cache_hit_bytes_percent', 'random_ios_percent', 'mirror_bytes_percent',
            'full_stripe_writes_bytes_percent', 'max_cpu_utilization', 'cpu_avg_utilization',
            'raid0_bytes_percent', 'raid1_bytes_percent', 'raid5_bytes_percent', 'raid6_bytes_percent',
            'ddp_bytes_percent', 'read_hit_response_time', 'write_hit_response_time',
            'combined_hit_response_time', 'max_possible_bps_under_current_load', 'max_possible_iops_under_current_load'
        ])


    def _identify_enrichment_fields(self, data: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Separate enrichment fields from genuine API fields.

        Returns:
            tuple: (api_fields, enrichment_fields)
        """
        # Known enrichment field patterns - these are added during processing, not from API
        enrichment_patterns = {
            # System identification enrichment
            'storage_system_name', 'storage_system_wwn',
            'system_name', 'system_wwn',
            'system_model', 'system_status', 'system_sub_model',
            'firmware_version', 'app_version', 'boot_version', 'nvsram_version',
            'chassis_serial_number', 'drive_count', 'tray_count', 'hot_spare_count',

            # Volume/host enrichment
            'host', 'host_group', 'storage_pool',

            # Drive enrichment
            'tray_id', 'vol_group_name', 'has_degraded_channel',
            'system_firmware_version', 'drive_slot', 'tray_ref',

            # Controller enrichment
            'controller_id', 'controller_label', 'controller_active', 'controller_model',
            'interface_type', 'is_management_interface', 'link_state', 'current_speed',
            'link_width', 'port_state', 'channel',

            # Capacity/space enrichment
            'used_pool_space', 'free_pool_space', 'unconfigured_space',
            'auto_load_balancing_enabled', 'host_connectivity_reporting_enabled',
            'remote_mirroring_enabled', 'security_key_enabled', 'simplex_mode_enabled',
            'drive_types'
        }

        api_fields = {}
        enrichment_fields = {}

        for key, value in data.items():
            if key in enrichment_patterns:
                enrichment_fields[key] = value
            else:
                api_fields[key] = value

        LOG.debug(f"Separated {len(api_fields)} API fields from {len(enrichment_fields)} enrichment fields")
        return api_fields, enrichment_fields

    def _validate_and_extract_fields_from_model(self, model_class, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use the model class to validate and extract properly typed fields from data.

        This method now gracefully handles enrichment fields by separating them from
        genuine API fields before validation, preventing model validation failures
        when enrichment data is present.
        """
        if not model_class or not hasattr(model_class, '__dataclass_fields__'):
            return {}

        # Separate enrichment fields from API fields to avoid validation conflicts
        api_fields, enrichment_fields = self._identify_enrichment_fields(data)

        # Log enrichment separation for debugging
        if enrichment_fields:
            LOG.debug(f"{model_class.__name__}: Found {len(enrichment_fields)} enrichment fields: {list(enrichment_fields.keys())}")

        # Use only API fields for model validation to avoid enrichment conflicts
        validation_data = api_fields.copy()

        fields = {}
        model_fields = model_class.__dataclass_fields__

        # DEBUG: Log the actual data keys for HostConfig
        if 'hostconfig' in str(model_class).lower():
            LOG.debug(f"HOST DATA DEBUG - validation_data keys: {list(validation_data.keys())}")
            LOG.debug(f"HOST DATA DEBUG - enrichment keys: {list(enrichment_fields.keys())}")

        for field_name, field_info in model_fields.items():
            # Skip internal fields and complex objects
            if field_name.startswith('_') or field_name in ['listOfMappings', 'metadata', 'perms', 'cache', 'cacheSettings', 'mediaScan']:
                continue

            # Skip complex nested objects for ethernet config (they're not useful for monitoring)
            if 'ethernetconfig' in str(model_class).lower():
                if field_name in ['dnsProperties', 'ntpProperties', 'physicalLocation',
                                'ipv6PortRoutableAddresses', 'supportedSpeedSettings']:
                    LOG.debug(f"Skipping complex ethernet field: {field_name}")
                    continue

            value = self._get_field_value(validation_data, field_name)
            # DEBUG: Log field processing for HostConfig
            if 'hostconfig' in str(model_class).lower():
                LOG.debug(f"HOST FIELD DEBUG - {field_name}: value={value}, type={type(value)}, is_none={value is None}")
            if value is None:
                continue

            # Get the type annotation
            field_type = field_info.type

            # Handle Optional types (extract the inner type)
            if hasattr(field_type, '__origin__') and field_type.__origin__ is Union:
                # Optional[T] is Union[T, None]
                non_none_types = [t for t in field_type.__args__ if t is not type(None)]
                if non_none_types:
                    field_type = non_none_types[0]

            try:
                # Convert based on the expected type
                if field_type == int:
                    if isinstance(value, int):
                        fields[field_name] = value
                    elif isinstance(value, str) and (value.isdigit() or (value.startswith('-') and value[1:].isdigit())):
                        fields[field_name] = int(value)
                    elif isinstance(value, float) and value == int(value):
                        fields[field_name] = int(value)
                    else:
                        LOG.debug(f"Skipping field {field_name}: cannot convert {type(value).__name__} {value} to int")

                elif field_type == float:
                    if isinstance(value, (int, float)):
                        fields[field_name] = float(value)
                    elif isinstance(value, str):
                        try:
                            fields[field_name] = float(value)
                        except ValueError:
                            LOG.debug(f"Skipping field {field_name}: cannot convert string '{value}' to float")
                    else:
                        LOG.debug(f"Skipping field {field_name}: cannot convert {type(value).__name__} to float")

                elif field_type == bool:
                    if isinstance(value, bool):
                        fields[field_name] = value  # Keep as boolean for proper InfluxDB line protocol
                    else:
                        LOG.debug(f"Skipping field {field_name}: expected bool, got {type(value).__name__}")

                elif field_type == str:
                    # Store string fields as InfluxDB fields (valuable data like host names, labels, etc.)
                    if isinstance(value, str) and value:  # Only store non-empty strings
                        # For ethernet config, skip fields that contain complex JSON objects
                        if 'ethernetconfig' in str(model_class).lower():
                            # Skip fields that typically contain JSON objects (IPv6 addresses, etc.)
                            if any(skip_pattern in field_name.lower() for skip_pattern in
                                   ['ipv6', 'dns', 'ntp', 'properties', 'address', 'addresses']):
                                if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                                    LOG.debug(f"Skipping ethernet JSON field: {field_name}")
                                    continue
                        fields[field_name] = value

                # Handle List[int] types by converting to comma-separated string
                elif hasattr(field_type, '__origin__') and field_type.__origin__ is list:
                    if field_type.__args__ and field_type.__args__[0] == int:
                        if isinstance(value, list) and all(isinstance(x, int) for x in value):
                            # Convert list of integers to comma-separated string for InfluxDB
                            fields[field_name] = ','.join(map(str, value))
                            LOG.debug(f"Converted List[int] field {field_name}: {value} -> {fields[field_name]}")
                        else:
                            LOG.debug(f"Skipping List[int] field {field_name}: invalid value {value}")
                    else:
                        LOG.debug(f"Skipping field {field_name}: unsupported list type {field_type}")

                else:
                    # For complex types, skip or handle specially
                    LOG.debug(f"Skipping field {field_name}: complex type {field_type}")

            except (ValueError, TypeError) as e:
                LOG.debug(f"Error converting field {field_name}: {e}")

        # Convert all field names to snake_case for consistent InfluxDB output
        converted_fields = {}
        for field_name, value in fields.items():
            snake_case_name = BaseModel.camel_to_snake(field_name)
            converted_fields[snake_case_name] = value

        # Add enrichment fields back to the output (they're important for tags)
        # Convert enrichment field names to snake_case as well
        for field_name, value in enrichment_fields.items():
            if value is not None:  # Only include non-None enrichment values
                # Skip system_id as it duplicates storage_system_wwn
                if field_name.lower() == 'system_id':
                    continue
                snake_case_name = BaseModel.camel_to_snake(field_name)
                converted_fields[snake_case_name] = value

        LOG.debug(f"{model_class.__name__}: Extracted {len(fields)} validated fields + {len(enrichment_fields)} enrichment fields")
        return converted_fields

    # === SCHEMA-BASED CONFIG CONVERSION METHODS ===

    def _convert_drive_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert drive configuration data using established patterns and schema-based conversion."""
        try:
            # Get standardized system identification tags
            system_tags = self._get_standardized_system_tags(data)

            # Extract basic drive identification tags
            tags = {
                'drive_id': self._sanitize_tag_value(str(self._get_field_value(data, 'driveRef') or 'unknown')),
                'drive_type': self._sanitize_tag_value(str(self._get_field_value(data, 'driveMediaType') or 'unknown')),
                'serial_number': self._sanitize_tag_value(str(self._get_field_value(data, 'serialNumber') or 'unknown')),
                'manufacturer': self._sanitize_tag_value(str(self._get_field_value(data, 'manufacturer') or 'unknown')),
                'status': self._sanitize_tag_value(str(self._get_field_value(data, 'status') or 'unknown')),
                **system_tags
            }

            # Add physical location tags if available (handle nested object)
            phys_loc = data.get('physicalLocation', {})
            if phys_loc and isinstance(phys_loc, dict):
                tags['slot'] = self._sanitize_tag_value(str(phys_loc.get('slot', 'unknown')))
                tags['tray_ref'] = self._sanitize_tag_value(str(phys_loc.get('trayRef', 'unknown')))
            else:
                tags['slot'] = 'unknown'
                tags['tray_ref'] = 'unknown'

            # Add pool information from enriched data
            tags['pool_name'] = self._sanitize_tag_value(str(data.get('pool_name', 'unknown')))

            # Extract fields using established patterns
            fields = {}

            # Boolean fields - convert to boolean for proper InfluxDB line protocol
            boolean_fields = ['available', 'hotSpare', 'offline', 'invalidDriveData', 'fdeCapable',
                            'fdeEnabled', 'fdeLocked', 'fipsCapable', 'hasDegradedChannel',
                            'nonRedundantAccess', 'sanitizeCapable', 'uncertified', 'dulbeCapable']

            for field_name in boolean_fields:
                value = self._get_field_value(data, field_name)
                if value is not None:
                    # Convert field name to snake_case for consistent output
                    snake_case_name = BaseModel.camel_to_snake(field_name)
                    fields[snake_case_name] = bool(value)

            # String fields - store as InfluxDB fields (valuable metadata)
            string_fields = ['cause', 'currentSpeed', 'currentVolumeGroupRef', 'driveSecurityType',
                           'firmwareVersion', 'lowestAlignedLBA', 'manufacturerDate', 'maxSpeed',
                           'mirrorDrive', 'phyDriveType', 'productID', 'softwareVersion',
                           'sparedForDriveRef', 'usableCapacity', 'worldWideName']

            for field_name in string_fields:
                value = self._get_field_value(data, field_name)
                if value is not None and str(value).strip():  # Only store non-empty strings
                    # Convert field name to snake_case for consistent output
                    snake_case_name = BaseModel.camel_to_snake(field_name)
                    fields[snake_case_name] = str(value)

            # Numeric fields
            numeric_fields = ['blkSize', 'blkSizePhysical', 'rawCapacity', 'spindleSpeed',
                            'volumeGroupIndex', 'workingChannel']

            for field_name in numeric_fields:
                value = self._get_field_value(data, field_name)
                if value is not None:
                    # Convert field name to snake_case for consistent output
                    snake_case_name = BaseModel.camel_to_snake(field_name)
                    try:
                        if isinstance(value, (int, float)):
                            fields[snake_case_name] = int(value) if field_name in ['blkSize', 'blkSizePhysical', 'spindleSpeed', 'volumeGroupIndex', 'workingChannel'] else float(value)
                        elif isinstance(value, str) and value.isdigit():
                            fields[snake_case_name] = int(value)
                        else:
                            # For capacity fields that might be string representations
                            fields[snake_case_name] = float(value)
                    except (ValueError, TypeError):
                        LOG.debug(f"Skipping non-numeric value for {field_name}: {value}")

            # NOTE: Configuration for nested field extraction (quick-fix approach)
            # TODO: This hardcoded config should be consolidated with other config dicts across 5+ files
            # TODO: When implementing schema-based nested field filtering, this section should be
            #       removed/replaced with per-model _nested_field_config in schema classes
            NESTED_FIELDS_CONFIG = {
                'ssdWearLife': {
                    'averageEraseCountPercent': ('ssd_average_erase_count_percent', float),
                    'percentEnduranceUsed': ('ssd_percent_endurance_used', float),
                    'spareBlocksRemainingPercent': ('ssd_spare_blocks_remaining_percent', float),
                    'isWearLifeMonitoringSupported': ('ssd_wear_life_monitoring_supported', bool)
                }
                # Additional nested objects can be added here as needed
                # 'physicalLocation': {...},  # Currently handled separately
                # 'hostInterfaces': {...},    # Too large, overlaps with config_interfaces
                # 'netInterfaces': {...}      # Too large, overlaps with config_interfaces
            }

            # Handle nested field extraction using configuration
            for nested_key, field_mappings in NESTED_FIELDS_CONFIG.items():
                nested_data = data.get(nested_key, {})
                if nested_data and isinstance(nested_data, dict):
                    for source_field, (target_field, field_type) in field_mappings.items():
                        value = nested_data.get(source_field)
                        if value is not None:
                            try:
                                fields[target_field] = field_type(value)
                            except (ValueError, TypeError):
                                LOG.debug(f"Invalid {nested_key}.{source_field}: {value}")

            # Handle nested interface type data (flatten like SAS data)
            interface_type_data = data.get('interfaceType', {})
            if interface_type_data and isinstance(interface_type_data, dict):
                # Extract SAS-specific fields if available
                sas_data = interface_type_data.get('sas', {})
                if sas_data and isinstance(sas_data, dict):
                    # Extract numeric SAS fields
                    for sas_field in ['channel', 'revision']:
                        sas_value = sas_data.get(sas_field)
                        if sas_value is not None:
                            try:
                                fields[f'sas_{sas_field}'] = int(sas_value)
                            except (ValueError, TypeError):
                                LOG.debug(f"Invalid SAS {sas_field} value: {sas_value}")

                    # Extract SAS boolean fields
                    if 'isDegraded' in sas_data:
                        fields['sas_is_degraded'] = bool(sas_data['isDegraded'])

                    # Extract SAS port addresses if available
                    port_addresses = sas_data.get('portAddresses', [])
                    if port_addresses and isinstance(port_addresses, list):
                        fields['sas_port_count'] = len(port_addresses)

            # Use current timestamp for config records (they don't have observedTime)
            timestamp = int(time.time())

            # Ensure we have at least one field for InfluxDB
            if not fields:
                fields['config_present'] = 1

            self._check_system_identification_tags(tags, measurement_name)

            return {
                'measurement': self.get_final_measurement_name(measurement_name),
                'tags': tags,
                'fields': fields,
                'time': timestamp
            }

        except Exception as e:
            LOG.warning(f"Error converting drive config record for {measurement_name}: {e}")
            # Fallback to basic conversion
            return self._convert_config_record(measurement_name, data)

    def _convert_volume_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert volume configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, VolumeConfig, {
            'volume_id': ('volumeRef', 'unknown'),
            'volume_name': ('volume_name', 'unknown'),
            'pool_id': ('pool_id', 'unknown'),
            'pool_name': ('pool_name', 'unknown'),
            'raid_level': ('raidLevel', 'unknown'),
            'volume_use': ('volumeUse', 'unknown'),
            'flash_cached': ('flashCached', 'false'),
            'status': ('status', 'unknown'),
            'pit_base_volume': ('pitBaseVolume', 'false'),
            'mapped': ('mapped', 'false'),
            'online_volume_copy': ('onlineVolumeCopy', 'false'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_controller_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert controller configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, ControllerConfig, {
            'controller_id': ('id', 'unknown'),
            'controller_unit': ('controller_unit', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_storage_pool_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert storage pool configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, StoragePoolConfig, {
            'pool_id': ('volumeGroupRef', 'unknown'),
            'pool_name': ('label', 'unknown'),
            'raid_level': ('raidLevel', 'unknown'),
            'blk_size_supported': ('blkSizeSupported', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_interface_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert interface configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, InterfaceConfig, {
            'interface_id': ('interfaceId', 'unknown'),
            'interface_type': ('interface_type', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_host_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert host configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, HostConfig, {
            'host_id': ('hostRef', 'unknown'),
            'host_name': ('label', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_host_group_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert host group configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, HostGroupsConfig, {
            'host_group_id': ('clusterRef', 'unknown'),
            'host_group_name': ('label', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_system_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert system configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, SystemConfig, {
            'storage_system_name': ('name', 'unknown'),
            'storage_system_wwn': ('wwn', 'unknown')
        }, [])

    def _convert_tray_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert tray configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, TrayConfig, {
            'tray_id': ('trayRef', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_volume_mapping_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert volume mapping configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, VolumeMappingsConfig, {
            'volume_id': ('volumeRef', 'unknown'),
            'host_id': ('mapRef', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_ethernet_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert ethernet configuration data using schema-based conversion."""
        return self._convert_schema_record(measurement_name, data, EthernetConfig, {
            'interface_id': ('interfaceRef', 'unknown'),
            'storage_system_name': ('storage_system_name', 'unknown'),
            'storage_system_wwn': ('storage_system_wwn', 'unknown')
        }, [])

    def _convert_snapshot_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert snapshot configuration data using schema-based conversion."""
        if 'group' in measurement_name.lower():
            return self._convert_schema_record(measurement_name, data, SnapshotGroups, {
                'snapshot_group_id': ('pitGroupRef', 'unknown'),
                'snapshot_group_name': ('name', 'unknown'),
                'storage_system_name': ('storage_system_name', 'unknown'),
                'storage_system_wwn': ('storage_system_wwn', 'unknown')
            }, [
                'snapshot_count', 'repository_capacity', 'max_repository_capacity',
                'percent_full', 'repository_utilization'
            ])
        elif 'schedule' in measurement_name.lower():
            return self._convert_schema_record(measurement_name, data, SnapshotSchedule, {
                'schedule_id': ('scheduleRef', 'unknown'),
                'schedule_name': ('name', 'unknown'),
                'target_object': ('targetObject', 'unknown'),
                'storage_system_name': ('storage_system_name', 'unknown'),
                'storage_system_wwn': ('storage_system_wwn', 'unknown')
            }, [
                'creation_time', 'last_run_time', 'next_run_time'
            ])
        elif 'image' in measurement_name.lower():
            return self._convert_schema_record(measurement_name, data, SnapshotImages, {
                'snapshot_image_id': ('pitRef', 'unknown'),
                'snapshot_group_id': ('pitGroupRef', 'unknown'),
                'storage_system_name': ('storage_system_name', 'unknown'),
                'storage_system_wwn': ('storage_system_wwn', 'unknown')
            }, [
                'creation_time', 'sequence_number', 'pit_capacity'
            ])
        else:
            # Fallback for other snapshot types
            return self._convert_config_record(measurement_name, data)

    def _convert_config_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert configuration data to InfluxDB record format."""
        LOG.debug(f"Converting config record for {measurement_name}")
        try:
            # Extract config type from measurement name (e.g., config_storage_pools -> storage_pools)
            config_type = measurement_name.replace('config_', '')

            # Create basic tags for configuration records
            # Special handling for system config which has raw field names
            if config_type == 'systemconfig':
                tags = {
                    'storage_system_name': self._sanitize_tag_value(str(
                        data.get('storage_system_name',  # Try enriched name first
                        data.get('name', 'unknown')))),  # Fall back to raw name
                    'storage_system_wwn': self._sanitize_tag_value(str(
                        data.get('storage_system_wwn',  # Try enriched wwn first
                        data.get('wwn', 'unknown'))))  # Fall back to raw wwn
                }
            else:
                tags = {
                    'storage_system_name': self._sanitize_tag_value(str(
                        data.get('storage_system_name', 'unknown'))),
                    'storage_system_wwn': self._sanitize_tag_value(str(
                        data.get('storage_system_wwn', 'unknown')))
                }

            # Add specific tags based on config type
            if 'storage_pool' in config_type:
                tags.update({
                    'pool_id': self._sanitize_tag_value(str(data.get('volumeGroupRef', data.get('id', 'unknown')))),
                    'pool_name': self._sanitize_tag_value(str(data.get('label', data.get('name', 'unknown')))),
                    'raid_level': self._sanitize_tag_value(str(data.get('raidLevel', 'unknown')))
                })
            elif 'volume' in config_type:
                tags.update({
                    'volume_id': self._sanitize_tag_value(str(data.get('volumeRef', data.get('id', 'unknown')))),
                    'volume_name': self._sanitize_tag_value(str(
                        data.get('volume_name',  # Use enriched volume_name first
                        data.get('label',
                        data.get('name', 'unknown'))))),
                    'pool_id': self._sanitize_tag_value(str(
                        data.get('pool_id',  # Use enriched pool_id first
                        data.get('volumeGroupRef', 'unknown')))),
                    'pool_name': self._sanitize_tag_value(str(
                        data.get('pool_name',  # Use enriched pool_name
                        data.get('volume_pool_name', 'unknown'))))
                })
            elif 'controller' in config_type:
                tags.update({
                    'controller_id': self._sanitize_tag_value(str(data.get('id', 'unknown'))),
                    'controller_status': self._sanitize_tag_value(str(data.get('status', 'unknown'))),
                    'controller_unit': self._sanitize_tag_value(str(data.get('controller_unit', 'unknown')))
                    # Don't put controllerRef in tags - it should only be a field
                    # 'controller_id': self._sanitize_tag_value(str(data.get('controllerRef', data.get('id', 'unknown')))),
                })
            elif 'drive' in config_type:
                # Note: Don't add id/status as tags - they will be extracted as fields by schema validation
                # Extract slot from nested physicalLocation
                physical_location = data.get('physicalLocation', {})
                drive_slot = physical_location.get('slot', 'unknown') if physical_location else 'unknown'

                # Debug logging for slot extraction
                LOG.debug(f"Drive config slot extraction - physicalLocation: {physical_location}, extracted slot: {drive_slot}")
                if drive_slot == 'unknown':
                    LOG.warning(f"Drive config missing slot info - data keys: {list(data.keys())}")

                tags.update({
                    'drive_type': self._sanitize_tag_value(str(data.get('driveMediaType', 'unknown'))),
                    'slot': self._sanitize_tag_value(str(drive_slot)),
                    'pool_name': self._sanitize_tag_value(str(data.get('pool_name', 'unknown')))
                    # Don't put driveRef in tags - it should only be a field
                    # 'drive_id': self._sanitize_tag_value(str(data.get('driveRef', data.get('id', 'unknown')))),
                    # Don't add these as tags to avoid conflicts with schema fields:
                    # 'drive_id': self._sanitize_tag_value(str(data.get('id', 'unknown'))),
                    # 'drive_status': self._sanitize_tag_value(str(data.get('status', 'unknown')))
                })
            elif 'tray' in config_type:
                # Note: Don't add serial_number as tag - it will be extracted as a field by schema validation
                # tags.update({
                #     'serial_number': self._sanitize_tag_value(str(data.get('serialNumber', 'unknown'))),
                # })
                # Don't put partNumber in tags - it may not be unique across multiple trays of same model
                # 'part_number': self._sanitize_tag_value(str(data.get('partNumber', 'unknown'))),
                pass  # No specific tags for tray config to avoid conflicts with schema fields
            elif 'hostgroups' in config_type:
                tags.update({
                    'hostgroup_id': self._sanitize_tag_value(str(data.get('hostgroup_id', data.get('clusterRef', data.get('id', 'unknown'))))),
                    'hostgroup_name': self._sanitize_tag_value(str(data.get('hostgroup_name', data.get('label', data.get('name', 'unknown')))))
                })
            elif 'host' in config_type and 'groups' not in config_type:
                # Host config - add hostgroup reference if available
                tags.update({
                    'host_id': self._sanitize_tag_value(str(data.get('host_id', data.get('hostRef', data.get('id', 'unknown'))))),
                    'host_name': self._sanitize_tag_value(str(data.get('host_name', data.get('label', data.get('name', 'unknown'))))),
                    'hostgroup_id': self._sanitize_tag_value(str(data.get('host_group_ref', data.get('clusterRef', 'unknown')))),
                    'hostgroup_name': self._sanitize_tag_value(str(data.get('hostgroup_name', 'unknown')))
                })
            elif 'interface' in config_type:
                # Get interface type from ioInterfaceTypeData.interfaceType with fallback to top-level interfaceType
                interface_type = 'unknown'
                if data.get('ioInterfaceTypeData') and isinstance(data.get('ioInterfaceTypeData'), dict):
                    interface_type = data['ioInterfaceTypeData'].get('interfaceType', 'unknown')
                elif data.get('interfaceType'):
                    interface_type = data.get('interfaceType')

                # Apply interface type classification logic (consistent with controller enrichment)
                if interface_type == 'pcie':
                    interface_type = 'other'  # PCIe interfaces are classified as 'other'
                elif interface_type == 'unknown':
                    # Check if this is an ethernet interface by interfaceRef pattern or presence of ethernet-specific fields
                    interface_ref = data.get('interfaceRef', '')
                    if interface_ref.startswith('28') or 'macAddr' in data or 'ipv4Address' in data:
                        interface_type = 'ethernet'

                tags.update({
                    'interface_id': self._sanitize_tag_value(str(data.get('interfaceRef', data.get('id', 'unknown')))),
                    'interface_type': self._sanitize_tag_value(str(interface_type)),
                    'controller_ref': self._sanitize_tag_value(str(data.get('controllerRef', 'unknown'))),
                    'controller_unit': self._get_controller_unit_from_id(str(data.get('controllerRef', 'unknown')))
                })
            elif 'ethernet' in config_type:
                # Ethernet interface configuration - management/network interfaces
                tags.update({
                    'interface_id': self._sanitize_tag_value(str(data.get('interfaceRef', data.get('id', 'unknown')))),
                    'interface_type': self._sanitize_tag_value(str(data.get('interfaceType', 'ethernet'))),
                    'controller_ref': self._sanitize_tag_value(str(data.get('controllerRef', 'unknown'))),
                    'controller_unit': self._get_controller_unit_from_id(str(data.get('controllerRef', 'unknown')))
                })
            else:
                # Generic config record - try to find common ID fields
                for id_field in ['id', 'ref', 'wwn', 'controllerRef', 'volumeRef']:
                    if id_field in data:
                        tags['config_id'] = self._sanitize_tag_value(str(data[id_field]))
                        break

            # Use schema-based validation to extract properly typed fields
            LOG.debug(f"Processing schema validation for {measurement_name}")
            model_class = self.schema_validator.get_model_class(measurement_name)
            LOG.debug(f"Found model class: {model_class}")

            if model_class:
                LOG.debug(f"Using schema validation for {measurement_name} with model {model_class.__name__}")
                fields = self._validate_and_extract_fields_from_model(model_class, data)
                LOG.debug(f"Extracted fields: {list(fields.keys())}")

                # Debug ethernet config field extraction specifically
                if 'ethernetconfig' in measurement_name:
                    LOG.info(f"ETHERNET DEBUG: Model class: {model_class.__name__}")
                    LOG.info(f"ETHERNET DEBUG: Extracted fields before exclusion: {list(fields.keys())}")
                    LOG.info(f"ETHERNET DEBUG: Sample field values: {dict(list(fields.items())[:5]) if fields else 'No fields'}")

                # Exclude fields that are already used as tags to avoid InfluxDB type conflicts
                tag_field_names = set(tags.keys())
                fields = {k: v for k, v in fields.items() if k not in tag_field_names}
                LOG.debug(f"Fields after tag exclusion: {list(fields.keys())}")

                # Debug ethernet config field exclusion
                if 'ethernetconfig' in measurement_name:
                    LOG.info(f"ETHERNET DEBUG: Tag field names: {tag_field_names}")
                    LOG.info(f"ETHERNET DEBUG: Fields after tag exclusion: {list(fields.keys())}")
                    LOG.info(f"ETHERNET DEBUG: Final field count: {len(fields)}")

                # Debug logging for capacity field
                if 'capacity' in fields:
                    LOG.debug(f"Schema-based capacity: value={fields['capacity']}, type={type(fields['capacity'])}")
            else:
                LOG.debug(f"No model class found for {measurement_name}, using fallback field extraction")
                # Fallback to basic field extraction for unknown measurements
                fields = {}
                numeric_config_fields = [
                    'capacity', 'totalSizeInBytes', 'usableCapacity', 'freeSpace', 'usedSpace',
                    'driveCount', 'volumeCount', 'sequenceNum', 'trayId', 'slot'
                ]

                for field_name in numeric_config_fields:
                    value = self._get_field_value(data, field_name)
                    if value is not None and isinstance(value, (int, float)):
                        # Convert field name to snake_case for consistent output
                        snake_case_name = BaseModel.camel_to_snake(field_name)
                        fields[snake_case_name] = value

                # Add boolean fields as integers (0/1)
                boolean_config_fields = ['active', 'offline', 'optimal', 'enabled', 'online', 'present']

                # Add hostgroup-specific numeric fields
                if 'hostgroup' in config_type:
                    numeric_config_fields.extend(['hostgroup_member_count'])

                for field_name in numeric_config_fields:
                    value = self._get_field_value(data, field_name)
                    if value is not None and isinstance(value, (int, float)):
                        # Convert field name to snake_case for consistent output
                        snake_case_name = BaseModel.camel_to_snake(field_name)
                        fields[snake_case_name] = value

                # Add boolean fields as integers (0/1)
                boolean_config_fields = ['active', 'offline', 'optimal', 'enabled', 'online', 'present']

                # Add hostgroup-specific boolean fields
                if 'hostgroup' in config_type:
                    boolean_config_fields.extend([
                        'hostgroup_sa_controlled', 'hostgroup_confirm_lun_mapping',
                        'hostgroup_pi_capable', 'hostgroup_lun0_restricted'
                    ])

                for field_name in boolean_config_fields:
                    value = data.get(field_name)
                    if isinstance(value, bool):
                        # Convert field name to snake_case for consistent output
                        snake_case_name = BaseModel.camel_to_snake(field_name)
                        fields[snake_case_name] = value  # Keep as boolean for proper InfluxDB line protocol

                # Add hostgroup-specific string fields
                if 'hostgroup' in config_type:
                    string_field = data.get('hostgroup_members')
                    if string_field and isinstance(string_field, str):
                        fields['hostgroup_members'] = string_field

            # Use current timestamp for config records (they don't have observedTime)
            import time
            timestamp = int(time.time())

            # Ensure we have at least one numeric field for InfluxDB
            if not fields:
                # If no numeric fields, add at least one field to make it a valid InfluxDB record
                fields['config_present'] = 1

            # For specific config types, try to extract additional numeric fields from raw data
            if 'interface' in config_type:
                # Extract basic numeric fields from nested InterfaceConfig data
                io_data = data.get('ioInterfaceTypeData', {})
                sas_data = io_data.get('sas', {}) if io_data else {}
                if sas_data:
                    # Extract numeric fields like channel, revision, isDegraded flag
                    # Only include numeric fields if they're present and valid
                    try:
                        ch = sas_data.get('channel')
                        if ch is not None and str(ch).strip() != '':
                            fields['channel'] = int(ch)
                    except (ValueError, TypeError):
                        LOG.debug(f"Invalid interface channel value (skipped): {sas_data.get('channel')}")

                    try:
                        rev = sas_data.get('revision')
                        if rev is not None and str(rev).strip() != '':
                            fields['revision'] = int(rev)
                    except (ValueError, TypeError):
                        LOG.debug(f"Invalid interface revision value (skipped): {sas_data.get('revision')}")

                    # isDegraded may be boolean; convert to int only when present
                    if 'isDegraded' in sas_data and sas_data['isDegraded'] is not None:
                        try:
                            fields['is_degraded'] = 1 if bool(sas_data['isDegraded']) else 0
                        except (ValueError, TypeError):
                            LOG.debug(f"Invalid isDegraded value (skipped): {sas_data.get('isDegraded')}")

            elif 'ethernet' in config_type:
                # Extract ethernet-specific fields (management interface configuration)
                # Most ethernet fields are handled by schema validation, but add any special numeric fields here
                pass

            elif 'tray' in config_type:
                # TrayConfig string fields (partNumber, serialNumber) are extracted by schema validation above
                # No additional numeric fields needed for tray config
                pass

            # Check system identification tags and log warning if unknown
            # Ensure canonical system tags are present (non-destructive)
            try:
                self._ensure_canonical_system_tags(tags, data)
            except Exception:
                LOG.debug("_ensure_canonical_system_tags failed", exc_info=True)
            self._check_system_identification_tags(tags, measurement_name)

            return {
                'measurement': self.get_final_measurement_name(measurement_name),
                'tags': tags,
                'fields': fields,
                'time': timestamp
            }

        except Exception as e:
            LOG.warning(f"Failed to convert config record {measurement_name}: {e}")
            return None

    def _convert_system_failures_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert system failures data to InfluxDB record format."""
        try:
            # Get standardized system identification tags
            system_tags = self._get_standardized_system_tags(data)

            # Create tags for system failure records based on SystemFailures model
            tags = {
                'failure_type': self._sanitize_tag_value(str(data.get('failureType', 'unknown'))),
                'object_type': self._sanitize_tag_value(str(data.get('objectType', 'unknown'))),
                **system_tags  # Include standardized system identification tags
            }

            # Fields for system failures - we need at least one numeric field for InfluxDB
            fields = {
                'failure_occurred': 1  # Simple indicator that failure occurred
            }

            # Add optional string fields as tags if they exist
            if 'objectRef' in data and data['objectRef']:
                tags['object_ref'] = self._sanitize_tag_value(str(data['objectRef']))

            if 'objectData' in data and data['objectData']:
                tags['object_data'] = self._sanitize_tag_value(str(data['objectData']))

            if 'extraData' in data and data['extraData']:
                tags['extra_data'] = self._sanitize_tag_value(str(data['extraData']))

            # Use current time as timestamp since system failures don't have observedTime
            import time
            timestamp = int(time.time())

            return {
                'measurement': self.get_final_measurement_name('events_system_failures'),
                'tags': tags,
                'fields': fields,
                'time': timestamp
            }

        except Exception as e:
            LOG.warning(f"Failed to convert system failures record: {e}")
            return None

    def _convert_schema_record(self, measurement_name: str, data: Dict[str, Any],
                             schema_class, tag_fields: Dict[str, tuple],
                             numeric_fields: List[str]) -> Optional[Dict[str, Any]]:
        """Generic conversion using schema model."""
        try:
            # Create schema instance from data
            schema_instance = schema_class.from_api_response(data)

            # DEBUG: Log when BaseModel objects are created in writer
            if hasattr(schema_instance, '__class__') and 'BaseModel' in str(type(schema_instance)):
                LOG.debug(f"Created BaseModel instance in _convert_schema_record: {type(schema_instance)} for {measurement_name}")

            # Extract tags using provided mapping
            tags = {}
            for tag_name, (field_name, default_value) in tag_fields.items():
                # Get value from schema instance using camelCase field name
                value = getattr(schema_instance, field_name, None)
                if value is None:
                    # Try getting from raw data via schema instance
                    value = schema_instance.get_raw(field_name, None)
                    if value is None:
                        # For enriched fields that may not be in schema, check original data dict
                        value = data.get(field_name, default_value)
                tags[tag_name] = self._sanitize_tag_value(str(value))

            # Add system identification tags from enriched data
            # Use the tag mapping for system tags if provided, otherwise fallback to enriched data
            if 'storage_system_name' not in tags:  # Only add if not already mapped
                system_name_value = data.get('system_name')
                if not system_name_value or system_name_value == 'unknown':
                    system_name_value = data.get('storage_system_name', 'unknown')
                tags['storage_system_name'] = self._sanitize_tag_value(str(system_name_value))
                # DEBUG: Log system name tag construction for drive stats
                if 'drive' in measurement_name.lower():
                    LOG.debug(f"Drive {measurement_name} system_name tag: data.system_name='{data.get('system_name')}', data.storage_system_name='{data.get('storage_system_name')}', final='{system_name_value}'")
            if 'storage_system_wwn' not in tags:  # Only add if not already mapped
                system_wwn_value = data.get('system_wwn')
                if not system_wwn_value or system_wwn_value == 'unknown':
                    system_wwn_value = data.get('storage_system_wwn', 'unknown')
                tags['storage_system_wwn'] = self._sanitize_tag_value(str(system_wwn_value))
                # DEBUG: Log system WWN tag construction for drive stats
                if 'drive' in measurement_name.lower():
                    LOG.debug(f"Drive {measurement_name} system_wwn tag: data.system_wwn='{data.get('system_wwn')}', data.storage_system_wwn='{data.get('storage_system_wwn')}', final='{system_wwn_value}'")

            # Extract numeric fields
            fields = {}
            for field_name in numeric_fields:
                # Convert snake_case to camelCase for schema access
                camel_field = BaseModel.snake_to_camel(field_name)
                value = getattr(schema_instance, camel_field, None)
                if value is None:
                    # Try getting from raw data
                    value = schema_instance.get_raw(camel_field, None)

                if value is not None:
                    # Use value as-is from model - schema defines appropriate types
                    fields[field_name] = value

            # Extract timestamp
            timestamp = self._extract_timestamp(data)

            # Clean up the schema instance reference to avoid BaseModel serialization issues
            del schema_instance

            if not fields:
                LOG.debug(f"No valid fields found for {measurement_name}")
                return None

            # Create the return record with primitive values only
            record = {
                'measurement': self.get_final_measurement_name(measurement_name),
                'tags': tags,
                'fields': fields,
                'time': timestamp
            }

            # Check system identification tags and log warning if unknown
            self._check_system_identification_tags(tags, measurement_name)

            # DEBUG: Check for BaseModel objects in the record before returning
            def find_basemodel_in_record(obj, path=""):
                if hasattr(obj, '__class__') and 'BaseModel' in str(type(obj)):
                    LOG.error(f"WRITER DEBUG: Found BaseModel in record at {path}: {type(obj)}")
                    return True
                elif isinstance(obj, dict):
                    for k, v in obj.items():
                        if find_basemodel_in_record(v, f"{path}.{k}"):
                            return True
                elif isinstance(obj, (list, tuple)):
                    for i, v in enumerate(obj):
                        if find_basemodel_in_record(v, f"{path}[{i}]"):
                            return True
                return False

            find_basemodel_in_record(record, f"{measurement_name}_record")

            return record

        except Exception as e:
            LOG.warning(f"Error converting {measurement_name} using schema: {e}")
            return None

    def _convert_generic_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert generic record data to InfluxDB record format.
        This method now handles only truly generic/unknown measurements since
        specific routing is handled by centralized categorization.
        """
        # Handle special wrapper case that doesn't fit normal categorization
        if measurement_name == 'performance_data':
            LOG.debug(f"Converting performance_data as volume performance record")
            return self._convert_volume_record(self.get_final_measurement_name('performance_data'), data)

        LOG.debug(f"Generic record conversion not implemented yet for {measurement_name}")
        return None

    def _convert_lockdown_status_record(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert lockdown status data to InfluxDB record format."""
        try:
            # Get standardized system identification tags
            system_tags = self._get_standardized_system_tags(data)

            tags = {
                'lockdown_state': self._sanitize_tag_value(str(self._get_field_value(data, 'lockdownState') or 'unknown')),
                **system_tags  # Include standardized system identification tags
            }

            # Extract fields (non-indexed data)
            fields = {
                'is_lockdown': 1 if self._get_field_value(data, 'isLockdown') else 0,
                'lockdown_type': str(self._get_field_value(data, 'lockdownType') or 'unknown')
                # Removed storage_system_name from fields - it's already a tag
                # 'storage_system_name': str(self._get_field_value(data, 'storageSystemLabel') or 'unknown')
            }

            # Add unlock key if present
            unlock_key_id = self._get_field_value(data, 'unlockKeyId')
            if unlock_key_id:
                fields['unlock_key_id'] = str(unlock_key_id)

            # Use current timestamp for lockdown status events
            timestamp = int(time.time())

            return {
                'measurement': self.get_final_measurement_name('events_lockdown_status'),
                'tags': tags,
                'fields': fields,
                'time': timestamp
            }

        except Exception as e:
            LOG.warning(f"Failed to convert lockdown status record: {e}")
            return None

    def _get_standardized_system_tags(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        Get standardized system identification tags from data.

        This method ensures all measurements use consistent storage_system_wwn and storage_system_name tags
        regardless of the input field naming conventions.

        Args:
            data: Dictionary containing system identification data

        Returns:
            Dictionary with standardized storage_system_wwn and storage_system_name tags
        """
        # Try to get WWN from various possible fields, in order of preference
        wwn_value = (
            data.get('storage_system_wwn') or
            data.get('system_wwn') or
            data.get('system_id') or
            self.system_id or
            'unknown'
        )

        # Try to get name from various possible fields, in order of preference
        name_value = (
            data.get('storage_system_name') or
            data.get('system_name') or
            self.system_name or
            'unknown'
        )

        # Ensure we don't use 'unknown' string as a valid value
        if wwn_value == 'unknown':
            wwn_value = self.system_id or 'unknown'
        if name_value == 'unknown' or name_value == 'json_replay_system':
            # json_replay_system is a placeholder that should be replaced
            if name_value == 'json_replay_system':
                LOG.warning(f"Found placeholder system name 'json_replay_system', falling back to system_name field")
            name_value = data.get('system_name') or self.system_name or 'unknown'

        return {
            'storage_system_wwn': self._sanitize_tag_value(str(wwn_value)),
            'storage_system_name': self._sanitize_tag_value(str(name_value))
        }

    def _ensure_canonical_system_tags(self, tags: Dict[str, str], data: Dict[str, Any]) -> None:
        """
        Non-destructively ensure canonical storage_system_name/storage_system_wwn tags exist.

        This will copy from common alias fields in the incoming `data` dict only when the
        canonical tag is missing or set to a placeholder. It does not remove any alias
        fields from the record and is safe to run multiple times.
        """
        # Helper to decide if a tag value is effectively missing
        def missing(val: Any) -> bool:
            return val is None or (isinstance(val, str) and (not val.strip() or val.strip().lower() in ('unknown', 'json_replay_system')))

        # Ensure WWN
        if missing(tags.get('storage_system_wwn')):
            wwn_candidates = [
                data.get('storage_system_wwn'),
                data.get('system_wwn'),
                data.get('system_id'),
                data.get('wwn'),
                self.system_id
            ]
            for c in wwn_candidates:
                if c and not missing(c):
                    tags['storage_system_wwn'] = self._sanitize_tag_value(str(c))
                    break

        # Ensure Name
        if missing(tags.get('storage_system_name')):
            name_candidates = [
                data.get('storage_system_name'),
                data.get('system_name'),
                data.get('name'),
                self.system_name
            ]
            for c in name_candidates:
                if c and not missing(c):
                    tags['storage_system_name'] = self._sanitize_tag_value(str(c))
                    break

    def _convert_environmental_power_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert environmental power data to InfluxDB record format."""
        try:
            LOG.debug(f"Converting environmental power record with system_id: {self.system_id}")
            # Accept both 'power' (JSON mode) and 'env_power' (live API mode)
            if data.get('measurement') in ['power', 'env_power']:
                # Handle both dict and list formats for 'data'
                raw_data = data.get('data')
                if isinstance(raw_data, dict):
                    fields = raw_data
                    tags = {}
                elif isinstance(raw_data, list):
                    # If it's a list, flatten and aggregate as needed
                    fields = {}
                    tags = {}
                    for item in raw_data:
                        if isinstance(item, dict):
                            fields.update(item)
                else:
                    LOG.warning(f"Unexpected env_power data format: {type(raw_data)}: {raw_data}")
                    return None

                # Get standardized system identification tags
                system_tags = self._get_standardized_system_tags(data)
                influx_tags = {
                    **system_tags,
                    'return_code': self._sanitize_tag_value(str(tags.get('return_code', 'unknown')))
                }

                influx_fields = {}
                for field_name, field_value in fields.items():
                    if field_value is not None:
                        if field_name == 'trayPower' and isinstance(field_value, list):
                            # Flatten tray power data into separate fields
                            for i, tray in enumerate(field_value):
                                if isinstance(tray, dict):
                                    tray_id = tray.get('trayID', i)
                                    influx_fields[f'tray_{tray_id}_number_of_power_supplies'] = int(tray.get('numberOfPowerSupplies', 0))
                                    input_power = tray.get('inputPower', [])
                                    if isinstance(input_power, list):
                                        for j, power in enumerate(input_power):
                                            influx_fields[f'tray_{tray_id}_psu_{j}_power'] = float(power)
                        elif isinstance(field_value, (int, float)):
                            # Convert field name to snake_case
                            snake_case_name = BaseModel.camel_to_snake(field_name)
                            influx_fields[snake_case_name] = field_value
                        elif isinstance(field_value, str):
                            # Convert field name to snake_case
                            snake_case_name = BaseModel.camel_to_snake(field_name)
                            try:
                                influx_fields[snake_case_name] = float(field_value)
                            except ValueError:
                                influx_fields[snake_case_name] = field_value
                        else:
                            # Convert field name to snake_case
                            snake_case_name = BaseModel.camel_to_snake(field_name)
                            influx_fields[snake_case_name] = field_value

                timestamp = int(time.time())
                self._check_system_identification_tags(influx_tags, 'env_power')
                return {
                    'measurement': self.get_final_measurement_name('env_power'),
                    'tags': influx_tags,
                    'fields': influx_fields,
                    'time': timestamp
                }
            else:
                LOG.warning(f"Invalid power data structure: {data}")
                return None
        except Exception as e:
            LOG.warning(f"Failed to convert environmental power record: {e}")
            return None

    def _convert_environmental_temperature_record(self, measurement_name: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert environmental temperature data to InfluxDB record format."""
        try:
            LOG.debug(f"Converting environmental temperature record with system_id: {self.system_id}")
            # Accept both 'temp' (JSON mode) and 'env_temperature' (live API mode)
            if data.get('measurement') in ['temp', 'env_temperature']:
                raw_data = data.get('data')
                influx_records = []
                if isinstance(raw_data, list):
                    for item in raw_data:
                        if isinstance(item, dict):
                            # Get standardized system identification tags
                            system_tags = self._get_standardized_system_tags(data)
                            influx_tags = {
                                'sensor_ref': self._sanitize_tag_value(str(item.get('thermalSensorRef', 'unknown'))),
                                **system_tags
                            }
                            influx_fields = {}
                            if 'currentTemp' in item:
                                influx_fields['temp'] = float(item['currentTemp'])
                            timestamp = int(time.time())
                            self._check_system_identification_tags(influx_tags, 'env_temperature')
                            influx_records.append({
                                'measurement': 'env_temperature',
                                'tags': influx_tags,
                                'fields': influx_fields,
                                'time': timestamp
                            })
                elif isinstance(raw_data, dict):
                    # Get standardized system identification tags
                    system_tags = self._get_standardized_system_tags(data)
                    influx_tags = {
                        'sensor_ref': self._sanitize_tag_value(str(raw_data.get('sensor_ref', 'unknown'))),
                        **system_tags
                    }
                    influx_fields = {}
                    if 'temp' in raw_data:
                        influx_fields['temp'] = float(raw_data['temp'])
                    timestamp = int(time.time())
                    self._check_system_identification_tags(influx_tags, 'env_temperature')
                    influx_records.append({
                        'measurement': 'env_temperature',
                        'tags': influx_tags,
                        'fields': influx_fields,
                        'time': timestamp
                    })
                else:
                    LOG.warning(f"Unexpected env_temperature data format: {type(raw_data)}: {raw_data}")
                    return None
                # Return first record for compatibility (could be extended to return all)
                return influx_records[0] if influx_records else None
            else:
                LOG.warning(f"Invalid temperature data structure: {data}")
                return None

        except Exception as e:
            LOG.warning(f"Failed to convert environmental temperature record: {e}")
            return None

    def _get_field_value(self, data_dict: Dict[str, Any], field_name: str) -> Any:
        """Get field value, trying both snake_case and camelCase variants using proper conversion."""

        # Try direct match first (field_name as-is)
        if field_name in data_dict:
            return data_dict[field_name]

        # Try proper snake_case conversion (for camelCase field names)
        from ..utils import camel_to_snake_case
        snake_case = camel_to_snake_case(field_name)
        if snake_case in data_dict:
            return data_dict[snake_case]

        # Try camelCase equivalent (for snake_case field names)
        from ..utils import snake_to_camel_case
        camel_case = snake_to_camel_case(field_name)
        if camel_case in data_dict:
            return data_dict[camel_case]

        return None

    def _extract_timestamp(self, data: Dict[str, Any]) -> int:
        """
        Extract timestamp from data, converting observedTimeInMS to seconds.

        Args:
            data: Record data dictionary

        Returns:
            int: Unix timestamp in seconds
        """
        # Try to get observedTimeInMS first
        observed_time_ms = self._get_field_value(data, 'observed_time_in_ms')
        if observed_time_ms:
            try:
                # Convert string milliseconds to seconds (round down)
                timestamp_ms = int(observed_time_ms)
                timestamp_s = timestamp_ms // 1000  # Integer division for second precision
                LOG.debug(f"Converted observedTimeInMS {timestamp_ms} to seconds: {timestamp_s}")
                return timestamp_s
            except (ValueError, TypeError):
                LOG.debug(f"Could not convert observedTimeInMS to int: {observed_time_ms}")

        # Try other timestamp fields
        observed_time = self._get_field_value(data, 'observed_time')
        if observed_time:
            try:
                # Parse ISO 8601 timestamp
                dt = datetime.fromisoformat(observed_time.replace('Z', '+00:00'))
                timestamp_s = int(dt.timestamp())  # Round down to seconds
                LOG.debug(f"Converted observedTime {observed_time} to seconds: {timestamp_s}")
                return timestamp_s
            except (ValueError, TypeError):
                LOG.debug(f"Could not parse observedTime: {observed_time}")

        # Default to current time in seconds (no nanosecond bloat)
        current_time = int(time.time())  # Already in seconds, rounded down
        LOG.debug(f"Using current timestamp: {current_time}")
        return current_time

    def _sanitize_tag_value(self, value: str) -> str:
        """Sanitize tag values to avoid InfluxDB line protocol issues."""
        if not value:
            return 'unknown'

        # Strip leading/trailing whitespace and collapse multiple spaces
        sanitized = ' '.join(value.split())

        # Replace spaces with underscores
        sanitized = sanitized.replace(' ', '_')

        # Remove or escape problematic characters for InfluxDB tags
        # InfluxDB doesn't like commas, spaces, equals signs in tag values
        sanitized = sanitized.replace(',', '_').replace('=', '_').replace('\n', '_').replace('\r', '_')

        # If empty after sanitization, return unknown
        if not sanitized.strip():
            return 'unknown'

        return sanitized

    def _sanitize_string_field(self, value: str) -> str:
        """Sanitize string field values by removing trailing/leading spaces and collapsing multiple spaces."""
        if not value:
            return ''

        # Strip leading/trailing whitespace and collapse multiple spaces
        sanitized = ' '.join(value.split())

        return sanitized

    def _get_controller_unit_from_id(self, controller_id: str) -> str:
        """Get controller unit designation (A/B) based on controller ID."""
        if not controller_id or controller_id == 'unknown':
            return 'unknown'

        # Simple logic: controllers ending with '1' are A, '2' are B
        # This matches the logic used in controller performance enrichment
        if controller_id.endswith('1'):
            return 'A'
        elif controller_id.endswith('2'):
            return 'B'
        else:
            return 'unknown'

    def get_batch_stats(self) -> Dict[str, Any]:
        """
        Get batching statistics from the client's automatic batching.

        Returns:
            Dictionary with batching statistics
        """
        if self.batch_callback:
            return self.batch_callback.get_stats()
        else:
            return {
                'writes': 0,
                'errors': 0,
                'retries': 0,
                'elapsed_ms': 0,
                'status': 'No callback available'
            }

    def close(self, timeout_seconds=90, force_exit_on_timeout=False):
        """Close the InfluxDB client connection with timeout.

        Args:
            timeout_seconds: Maximum time to wait for graceful close (default: 90s)
            force_exit_on_timeout: If True, force process exit after timeout to avoid zombie threads
        """
        if not self.client:
            return

        import threading
        import time

        timeout_seconds = 90  # Match the client timeout (60s) + buffer for container shutdowns
        LOG.info(f"Closing InfluxDB client with {timeout_seconds}s timeout...")        # Use a flag to track if close completed
        close_completed = threading.Event()
        close_error = []

        def close_thread():
            try:
                if self.client and hasattr(self.client, 'close') and callable(getattr(self.client, 'close')):
                    LOG.info("Calling InfluxDB client close() method")
                    start_close = time.time()
                    self.client.close()
                    close_elapsed = time.time() - start_close
                    LOG.info(f"InfluxDB client closed gracefully in {close_elapsed:.2f}s")
                close_completed.set()
            except Exception as e:
                close_error.append(e)
                LOG.warning(f"Error during graceful close: {e}")
                close_completed.set()

        # Start close in background thread
        closer = threading.Thread(target=close_thread, daemon=True)
        closer.start()

        # Wait for completion or timeout
        if close_completed.wait(timeout_seconds):
            if close_error:
                LOG.warning(f"Close completed with errors: {close_error[0]}")
            else:
                LOG.info("InfluxDB client closed successfully within timeout")
                # Even successful close may leave zombie threads - give them 5s to cleanup
                LOG.info("Waiting 5s for background threads to cleanup...")
                import time
                time.sleep(5)
        else:
            LOG.warning(f"InfluxDB client close timed out after {timeout_seconds}s - forcing shutdown")
            LOG.info("Pending writes may be lost, but avoiding indefinite hang")

        # Clear reference regardless
        self.client = None

        # Handle force exit option
        if not close_completed.is_set() and force_exit_on_timeout:
            LOG.warning("Force exit requested after timeout - terminating process")
            LOG.warning("Some background writes may be lost, but preventing indefinite hang")
            import sys
            sys.exit(1)

        # Log warning but don't force exit - allow process to continue for next iteration
        if not close_completed.is_set():
            LOG.warning("InfluxDB client close timed out - proceeding without forced exit to allow iteration continuation")
            LOG.info("Process will continue - data preservation may be incomplete but iteration loop can proceed")

    def _write_debug_input_json(self, measurements: Dict[str, Any], loop_iteration: int = 1):
        """
        Write input measurements to JSON file for debugging/validation.
        Only enabled when COLLECTOR_LOG_LEVEL=DEBUG.
        """
        if not self.enable_debug_output:
            return

        try:
            # Ensure output directory exists
            os.makedirs(self.debug_output_dir, exist_ok=True)

            # Use iteration-based filename to preserve iteration 1's config data
            if loop_iteration == 1:
                filename = "iteration_1_influxdb_writer_input_final.json"
            else:
                filename = "influxdb_writer_input_final.json"
            filepath = os.path.join(self.debug_output_dir, filename)

            # Convert data to JSON-serializable format
            serializable_data = {}
            for measurement_name, measurement_data in measurements.items():
                if measurement_data:  # Only include non-empty measurements
                    serializable_data[measurement_name] = []
                    if isinstance(measurement_data, list):
                        for item in measurement_data:
                            # Normalize to dict format
                            if hasattr(item, '__dict__'):
                                item_dict = item.__dict__
                            elif isinstance(item, dict):
                                item_dict = item
                            else:
                                item_dict = {"value": str(item)}
                            serializable_data[measurement_name].append(item_dict)
                    else:
                        # Single item
                        if hasattr(measurement_data, '__dict__'):
                            item_dict = measurement_data.__dict__
                        elif isinstance(measurement_data, dict):
                            item_dict = measurement_data
                        else:
                            item_dict = {"value": str(measurement_data)}
                        serializable_data[measurement_name] = [item_dict]

            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, indent=2, default=str)

            LOG.info(f"InfluxDB writer input JSON saved to: {filepath}")

        except Exception as e:
            LOG.error(f"Failed to write InfluxDB debug input JSON: {e}")

    def _write_debug_line_protocol(self, measurements: Dict[str, Any], loop_iteration: int = 1):
        """
        Write generated line protocol to text file for debugging/validation.
        Only enabled when COLLECTOR_LOG_LEVEL=DEBUG.
        """
        if not self.enable_debug_output:
            return

        try:
            import os
            from datetime import datetime

            # Ensure output directory exists
            os.makedirs(self.debug_output_dir, exist_ok=True)

            # Use iteration-based filename to preserve iteration 1's config data
            if loop_iteration == 1:
                filename = "iteration_1_influxdb_line_protocol_final.txt"
            else:
                filename = "influxdb_line_protocol_final.txt"
            filepath = os.path.join(self.debug_output_dir, filename)

            # Generate line protocol for all measurements
            line_protocol_lines = []

            for measurement_name, measurement_data in measurements.items():
                if not measurement_data:
                    continue

                # Convert to line protocol format (reuse existing logic)
                records = self._convert_to_line_protocol(measurement_name, measurement_data)

                for record in records:
                    try:
                        # Convert record dict to InfluxDB line protocol format
                        line = self._record_to_line_protocol(record)
                        if line:
                            line_protocol_lines.append(line)
                    except Exception as e:
                        LOG.debug(f"Failed to convert record to line protocol: {e}")
                        continue

            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                for line in line_protocol_lines:
                    f.write(line + '\n')

            LOG.info(f"InfluxDB line protocol debug output saved to: {filepath} ({len(line_protocol_lines)} lines)")

        except Exception as e:
            LOG.error(f"Failed to write InfluxDB debug line protocol: {e}")

    def _record_to_line_protocol(self, record: Dict[str, Any]) -> str:
        """
        Convert a record dictionary to InfluxDB line protocol string format.

        Format: measurement,tag1=value1,tag2=value2 field1=value1,field2=value2 timestamp
        """
        try:
            measurement = record.get('measurement', 'unknown')
            tags = record.get('tags', {})
            fields = record.get('fields', {})
            timestamp = record.get('time', int(time.time()))

            # Build measurement name
            line_parts = [measurement]

            # Add tags
            if tags:
                tag_parts = []
                for tag_key, tag_value in sorted(tags.items()):
                    if tag_value is not None:
                        # Escape special characters in tag keys and values
                        escaped_key = str(tag_key).replace(',', r'\,').replace(' ', r'\ ').replace('=', r'\=')
                        escaped_value = str(tag_value).replace(',', r'\,').replace(' ', r'\ ').replace('=', r'\=')
                        tag_parts.append(f"{escaped_key}={escaped_value}")

                if tag_parts:
                    line_parts[0] += ',' + ','.join(tag_parts)

            # Add fields (ensure space separator between tags and fields)
            if fields:
                field_parts = []
                for field_key, field_value in sorted(fields.items()):
                    if field_value is not None:
                        # Escape field key
                        escaped_key = str(field_key).replace(',', r'\,').replace(' ', r'\ ').replace('=', r'\=')

                        # Format field value based on type
                        if isinstance(field_value, str):
                            # String field - sanitize and quote
                            sanitized_value = self._sanitize_string_field(field_value)
                            escaped_value = sanitized_value.replace('"', r'\"').replace('\\', r'\\')
                            formatted_value = f'"{escaped_value}"'
                        elif isinstance(field_value, bool):
                            # Boolean field
                            formatted_value = 'true' if field_value else 'false'
                        elif isinstance(field_value, int):
                            # Integer field - add 'i' suffix
                            formatted_value = f"{field_value}i"
                        elif isinstance(field_value, float):
                            # Float field
                            formatted_value = str(field_value)
                        else:
                            # Default to string representation - sanitize first
                            sanitized_value = self._sanitize_string_field(str(field_value))
                            escaped_value = sanitized_value.replace('"', r'\"').replace('\\', r'\\')
                            formatted_value = f'"{escaped_value}"'

                        field_parts.append(f"{escaped_key}={formatted_value}")

                if field_parts:
                    # Add space before fields section for proper line protocol format
                    line_parts.append(' ' + ','.join(field_parts))
                else:
                    # No valid fields - skip this record
                    return ""
            else:
                # No fields - skip this record
                return ""

            # Add timestamp (in seconds, converted to nanoseconds for line protocol)
            line_parts.append(' ' + str(int(timestamp) * 1_000_000_000))

            return ''.join(line_parts)

        except Exception as e:
            LOG.debug(f"Failed to convert record to line protocol: {e}")
            return ""

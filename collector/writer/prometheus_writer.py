"""
Dynamic Prometheus exporter writer for E-Series Performance Analyzer.
Automatically generates metrics from analyzed_* performance data structures.
"""

import logging
import threading
import os
from typing import Dict, Any, List, Union, Optional
from datetime import datetime
from prometheus_client import Gauge, CollectorRegistry, start_http_server, generate_latest

from .base import Writer
from ..schema.base_model import BaseModel
from ..config.endpoint_categories import should_export_to_prometheus

# Initialize logger
LOG = logging.getLogger(__name__)

class PrometheusWriter(Writer):
    """
    Dynamic Prometheus writer that automatically generates metrics from analyzed_* data structures.
    This approach removes the need for manual metric definitions and captures all available fields.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize Dynamic Prometheus Writer.

        Args:
            config: Optional configuration dictionary
        """
        config = config or {}

        # Configuration with defaults
        self.port = config.get('prometheus_port', 9090)

        # Debug output configuration - factory provides directory or None
        self.debug_output_dir = config.get('json_output_dir')
        self.enable_debug_output = self.debug_output_dir is not None

        if self.enable_debug_output:
            LOG.info(f"Prometheus debug file output enabled -> {self.debug_output_dir}")

        # Legacy configuration support (for backward compatibility)
        self.enable_json_output = config.get('enable_json_output', self.enable_debug_output)
        self.enable_html_output = config.get('enable_html_output', self.enable_debug_output)

        # Create separate registry for this writer
        self.prometheus_registry = CollectorRegistry()

        # Dynamic metrics storage - metrics created on-demand
        self.dynamic_metrics: Dict[str, Gauge] = {}

        # Server management
        self.server_lock = threading.Lock()
        self.server_started = False

        # Field filtering for cleaner metrics
        self.excluded_fields = {
            'timestamp', 'time', 'id', 'object_id', 'index',
            'statistics', 'stat_list', 'data', 'items',
            'measurement_name', 'measurement_type', 'source',
            'collection_timestamp'
        }

        # Metrics that should be treated as rates (per second)
        self.rate_metrics = {
            'iops', 'throughput', 'bandwidth', 'operations', 'requests'
        }

        # Common label mappings for different measurement types
        self.label_mappings = {
            'volume': ['system_id', 'storage_system_name', 'volume_id', 'volume_name', 'host', 'host_group', 'storage_pool', 'controller_id'],
            'drive': ['system_id', 'storage_system_name', 'sys_tray', 'sys_tray_slot', 'vol_group_name', 'drive_id'],
            'controller': ['system_id', 'storage_system_name', 'controller_id'],
            'interface': ['system_id', 'storage_system_name', 'interface_id', 'channel_type'],
            'system': ['system_id', 'storage_system_name'],
            'power': ['system_id', 'storage_system_name'],
            'temp': ['system_id', 'storage_system_name', 'sensor', 'sensor_seq']
        }

        LOG.info("PrometheusWriter initialized with dynamic metric generation")

    def _sanitize_label_value(self, value: Any) -> str:
        """Sanitize label values to avoid Prometheus metric issues."""
        if value is None:
            return 'unknown'

        # Convert to string and strip whitespace
        value_str = str(value).strip()
        if not value_str:
            return 'unknown'

        # Replace spaces with underscores and handle problematic characters
        sanitized = value_str.replace(' ', '_').replace(',', '_').replace('=', '_')
        sanitized = sanitized.replace('\n', '_').replace('\r', '_').replace('"', '_')

        # Remove leading/trailing underscores
        sanitized = sanitized.strip('_')

        if not sanitized:
            return 'unknown'

        return sanitized

    def _sanitize_metric_name(self, base_name: str, field_name: str) -> str:
        """Create a valid Prometheus metric name from measurement and field names."""
        # Convert to lowercase and replace problematic characters
        base_clean = base_name.lower().replace('performance_', '').replace('analyzed_', '').replace('_statistics', '')

        # Convert camelCase to snake_case using regex
        import re

        # Insert underscore before capital letters (but not at the start)
        field_snake = re.sub(r'(?<!^)([A-Z])', r'_\1', field_name).lower()

        # Handle specific acronyms and abbreviations for better readability
        field_snake = field_snake.replace('i_ops', 'iops')  # IOps -> iops
        field_snake = field_snake.replace('std_dev', 'stddev')  # StdDev -> stddev
        field_snake = field_snake.replace('i_d', 'id')  # Id -> id
        field_snake = field_snake.replace('u_r_l', 'url')  # URL -> url
        field_snake = field_snake.replace('h_t_t_p', 'http')  # HTTP -> http

        # Remove non-alphanumeric characters except underscores
        base_clean = re.sub(r'[^a-z0-9_]', '', base_clean)
        field_snake = re.sub(r'[^a-z0-9_]', '', field_snake)

        # Remove any double underscores
        field_snake = re.sub(r'_{2,}', '_', field_snake)

        # Construct the metric name with appropriate prefix
        if any(env_indicator in base_name.lower() for env_indicator in ['env_power', 'power', 'env_temperature', 'temp']):
            # Environmental metrics get env_ prefix (remove redundant env_ from base_name)
            clean_base = base_clean.replace('env_', '')
            metric_name = f"env_{clean_base}_{field_snake}"
        elif any(event_indicator in base_name.lower() for event_indicator in ['events_system_failures', 'events_lockdown_status']):
            # Event metrics get event_ prefix (remove redundant events_ from base_name)
            clean_base = base_clean.replace('events_', '')
            metric_name = f"event_{clean_base}_{field_snake}"
        else:
            # Performance metrics get performance_ prefix
            metric_name = f"performance_{base_clean}_{field_snake}"

        # Ensure it starts with a letter
        if metric_name[0].isdigit():
            metric_name = f"metric_{metric_name}"

        # Remove leading/trailing underscores
        metric_name = metric_name.strip('_')

        return metric_name

    def _determine_metric_type(self, measurement_name: str, field_name: str) -> str:
        """Determine the appropriate metric type and units for a field."""
        field_lower = field_name.lower()

        # Time-based metrics (convert to seconds)
        if 'time' in field_lower or 'latency' in field_lower or 'response' in field_lower:
            return 'seconds'

        # Throughput/bandwidth metrics (bytes per second)
        if 'throughput' in field_lower or 'bandwidth' in field_lower:
            return 'bytes_per_second'

        # IOPS metrics
        if 'iops' in field_lower or 'operations' in field_lower:
            return 'total'

        # Percentage metrics
        if 'percent' in field_lower or 'utilization' in field_lower or 'hit' in field_lower:
            return 'percent'

        # Temperature
        if 'temp' in measurement_name.lower() and ('celsius' in field_lower or 'temperature' in field_lower):
            return 'celsius'

        # Power
        if 'power' in measurement_name.lower() and ('watts' in field_lower or 'power' in field_lower):
            return 'watts'

        # Default to total for numeric values
        return 'total'

    def _get_metric_help_text(self, measurement_name: str, field_name: str, metric_type: str) -> str:
        """Generate helpful description for the metric."""
        base_name = measurement_name.replace('performance_', '').replace('analyzed_', '').replace('_statistics', '').title()
        field_title = field_name.replace('_', ' ').title()

        type_suffix = {
            'seconds': ' in seconds',
            'bytes_per_second': ' in bytes per second',
            'total': ' total',
            'percent': ' percentage',
            'celsius': ' in Celsius',
            'watts': ' in watts'
        }.get(metric_type, '')

        return f"{base_name} {field_title}{type_suffix}"

    def _extract_labels(self, data_dict: Dict[str, Any], measurement_type: str) -> Dict[str, str]:
        """Extract appropriate labels for a measurement type."""
        labels = {}

        # Get label mapping for this measurement type
        label_fields = self.label_mappings.get(measurement_type, ['system_id', 'storage_system_name'])

        # Common label mappings from data fields - simplified to use standard field names
        field_mappings = {
            'system_id': ['system_id'],
            'storage_system_name': ['storage_system_name'],
            'volume_id': ['volume_id', 'volumeId'],
            'volume_name': ['volume_name', 'volumeName'],
            'host': ['host', 'hostname'],
            'host_group': ['host_group', 'hostGroup'],
            'storage_pool': ['storage_pool', 'storagePool', 'pool_name'],
            'controller_id': ['controller_id', 'controllerId'],
            'sys_tray': ['tray_id', 'trayId', 'sys_tray'],
            'sys_tray_slot': ['drive_slot', 'driveSlot', 'slot', 'sys_tray_slot'],
            'vol_group_name': ['vol_group_name', 'volGroupName', 'volume_group'],
            'drive_id': ['drive_id', 'driveId'],
            'interface_id': ['interface_id', 'interfaceId'],
            'channel_type': ['channel_type', 'channelType', 'type'],
            'sensor': ['sensor', 'sensor_name', 'sensorName'],
            'sensor_seq': ['sensor_seq', 'sensorSeq', 'sequence', 'seq']
        }

        # Extract labels based on the mapping
        for label_name in label_fields:
            value = None
            for field_variant in field_mappings.get(label_name, [label_name]):
                if field_variant in data_dict:
                    value = data_dict[field_variant]
                    break

            labels[label_name] = self._sanitize_label_value(value)

        return labels

    def _get_or_create_metric(self, measurement_name: str, field_name: str, labels: Dict[str, str]) -> Optional[Gauge]:
        """Get or create a Prometheus metric for a specific field."""
        try:
            metric_name = self._sanitize_metric_name(measurement_name, field_name)

            if metric_name not in self.dynamic_metrics:
                # Create new metric
                metric_type = self._determine_metric_type(measurement_name, field_name)
                help_text = self._get_metric_help_text(measurement_name, field_name, metric_type)
                label_names = list(labels.keys())

                self.dynamic_metrics[metric_name] = Gauge(
                    metric_name,
                    help_text,
                    label_names,
                    registry=self.prometheus_registry
                )

                LOG.debug(f"Created new metric: {metric_name} with labels: {label_names}")

            return self.dynamic_metrics[metric_name]

        except Exception as e:
            LOG.error(f"Error creating metric {measurement_name}.{field_name}: {e}")
            return None

    def _process_data_item_dynamically(self, measurement_name: str, data_item: Any):
        """Process a single data item and create metrics for all numeric fields."""
        try:
            # Normalize to dictionary
            if hasattr(data_item, '__dict__'):
                data_dict = data_item.__dict__
            elif isinstance(data_item, dict):
                data_dict = data_item
            else:
                LOG.warning(f"Cannot process data item type: {type(data_item)}")
                return

            # Determine measurement type for label extraction
            measurement_type = 'system'  # default
            if 'volume' in measurement_name:
                measurement_type = 'volume'
            elif 'drive' in measurement_name:
                measurement_type = 'drive'
            elif 'controller' in measurement_name:
                measurement_type = 'controller'
            elif 'interface' in measurement_name:
                measurement_type = 'interface'
            elif 'power' in measurement_name.lower():
                measurement_type = 'power'
            elif 'temp' in measurement_name.lower():
                measurement_type = 'temp'

            # Extract common labels for this measurement type
            labels = self._extract_labels(data_dict, measurement_type)

            # Special handling for environmental data with nested structure
            '''
            "energyStarData": {
                "totalPower": 659,
                "numberOfTrays": 1,
                "trayPower": [
                {
                    "trayID": 99,
                    "numberOfPowerSupplies": 2,
                    "inputPower": [
                    333,
                    326
                    ]
                }
                ]
            }
            '''
            fields_to_process = {}
            if 'data' in data_dict:
                if isinstance(data_dict['data'], dict):
                    # Environmental power data: flatten the nested 'data' object
                    fields_to_process.update(data_dict['data'])
                    # LOG.debug(f"Flattened 'data' object for processing: {data_dict['data'].keys()}")
                    # Extract detailed PSU metrics from trayPower array
                    if 'trayPower' in data_dict['data'] and isinstance(data_dict['data']['trayPower'], list):
                        for tray in data_dict['data']['trayPower']:
                            if isinstance(tray, dict):
                                tray_id = tray.get('trayID', 'unknown')

                                # Add PSU count for this tray
                                if 'numberOfPowerSupplies' in tray:
                                    fields_to_process[f'tray_{tray_id}_psu_count'] = tray['numberOfPowerSupplies']

                                # Add individual PSU power readings
                                if 'inputPower' in tray and isinstance(tray['inputPower'], list):
                                    for psu_idx, power_value in enumerate(tray['inputPower']):
                                        if isinstance(power_value, (int, float)):
                                            fields_to_process[f'tray_{tray_id}_psu_{psu_idx}_power'] = power_value

                elif isinstance(data_dict['data'], list):
                    # Environmental temperature data: process each sensor in the array
                    for i, sensor_data in enumerate(data_dict['data']):
                        if isinstance(sensor_data, dict):
                            for k, v in sensor_data.items():
                                # Create unique field names for each sensor
                                if k == 'currentTemp':
                                    fields_to_process[f'temp_sensor_{i}'] = v
                                elif k == 'thermalSensorRef':
                                    # Store sensor reference as label instead of metric
                                    data_dict[f'sensor_ref_{i}'] = v
                # Also include top-level fields
                for k, v in data_dict.items():
                    if k != 'data':
                        fields_to_process[k] = v
                        # LOG.debug(f"Top-level field added for processing: {k}={v}")


            else:
                # Regular data: use all fields directly
                fields_to_process = data_dict

            # Process all numeric fields
            metrics_created = 0
            for field_name, field_value in fields_to_process.items():
                # Skip excluded fields
                if field_name.lower() in self.excluded_fields:
                    continue

                # Skip non-numeric fields
                if not isinstance(field_value, (int, float)):
                    continue

                # Skip null/invalid values
                if field_value is None or (isinstance(field_value, float) and not (field_value == field_value)):  # NaN check
                    continue

                # Create and set metric
                metric = self._get_or_create_metric(measurement_name, field_name, labels)
                if metric:
                    metric.labels(**labels).set(float(field_value))
                    metrics_created += 1

            if metrics_created > 0:
                LOG.debug(f"Created {metrics_created} metrics for {measurement_type} item")

        except Exception as e:
            LOG.error(f"Error processing data item for {measurement_name}: {e}")

    def _start_prometheus_server(self):
        """Start the Prometheus HTTP server if not already started."""
        with self.server_lock:
            if not self.server_started:
                try:
                    start_http_server(self.port, registry=self.prometheus_registry)
                    self.server_started = True
                    LOG.info(f"Prometheus metrics server started on port {self.port}")
                except Exception as e:
                    LOG.error(f"Failed to start Prometheus server on port {self.port}: {e}")
                    raise

    def write(self, data: Dict[str, Any], loop_iteration: int = 1) -> bool:
        """
        Write data to Prometheus metrics using dynamic generation.

        Args:
            data: Dictionary containing measurement data
            loop_iteration: Current iteration number for debug file naming

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Apply schema-based validation if available
            try:
                from ..validator.schema_validator import validate_measurements_for_influxdb
                data = validate_measurements_for_influxdb(data)
                LOG.debug("Schema validation completed successfully")
            except Exception as e:
                LOG.debug(f"Schema validation not available or failed: {e}")

            # Start the metrics server if not already started
            if not self.server_started:
                self._start_prometheus_server()

            LOG.info(f"PrometheusWriter processing {len(data)} measurement types")

            # Process each measurement type in the data
            measurements_processed = 0
            total_metrics_created = 0

            for measurement_name, measurement_data in data.items():
                if should_export_to_prometheus(measurement_name):
                    LOG.info(f"Processing {measurement_name}: {len(measurement_data) if hasattr(measurement_data, '__len__') else 0} items")

                    # Process each item in the measurement data
                    if isinstance(measurement_data, list):
                        for item in measurement_data:
                            self._process_data_item_dynamically(measurement_name, item)
                    else:
                        self._process_data_item_dynamically(measurement_name, measurement_data)

                    measurements_processed += 1
                else:
                    LOG.debug(f"Skipping measurement not configured for Prometheus export: {measurement_name}")

            total_metrics_created = len(self.dynamic_metrics)

            # Write debug outputs - match InfluxDB writer pattern
            if self.enable_debug_output:
                self._write_debug_input_json(data, loop_iteration)
                self._write_debug_metrics_output(loop_iteration)

            LOG.info(f"Processed {measurements_processed} measurement types, created {total_metrics_created} unique metrics")
            return True

        except Exception as e:
            LOG.error(f"Error writing to Prometheus: {e}", exc_info=True)
            return False

    def _should_process_for_prometheus(self, measurement_name: str) -> bool:
        """
        Determine if a measurement should be processed for Prometheus using centralized configuration.
        This replaces the old hardcoded _is_performance_measurement logic.
        """
        return should_export_to_prometheus(measurement_name)

    def _write_debug_input_json(self, measurements: Dict[str, Any], loop_iteration: int = 1):
        """
        Write input measurements to JSON file for debugging/validation.
        Only enabled when COLLECTOR_LOG_LEVEL=DEBUG.
        Matches InfluxDB writer pattern exactly.
        """
        if not self.enable_debug_output:
            return

        try:
            import json
            import os
            from datetime import datetime

            # Ensure output directory exists
            os.makedirs(self.debug_output_dir, exist_ok=True)

            # Use iteration-based filename to preserve iteration 1's config data
            if loop_iteration == 1:
                filename = "iteration_1_prometheus_writer_input_final.json"
            else:
                filename = "prometheus_writer_input_final.json"
            filepath = os.path.join(self.debug_output_dir, filename)

            # Convert data to JSON-serializable format (only measurements configured for Prometheus)
            serializable_data = {}
            for measurement_name, measurement_data in measurements.items():
                if measurement_data and should_export_to_prometheus(measurement_name):
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

            LOG.info(f"Prometheus writer input JSON saved to: {filepath}")

        except Exception as e:
            LOG.error(f"Failed to write Prometheus debug input JSON: {e}")

    def _write_debug_metrics_output(self, loop_iteration: int = 1):
        """
        Write generated Prometheus metrics to text file for debugging/validation.
        Only enabled when COLLECTOR_LOG_LEVEL=DEBUG.
        Matches InfluxDB writer pattern exactly.
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
                filename = "iteration_1_prometheus_metrics_final.txt"
            else:
                filename = "prometheus_metrics_final.txt"
            filepath = os.path.join(self.debug_output_dir, filename)

            # Generate Prometheus metrics in text format
            metrics_text = generate_latest(self.prometheus_registry).decode('utf-8')

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("# Dynamic Prometheus Metrics Export\n")
                f.write(f"# Generated: {datetime.now().isoformat()}\n")
                f.write("# Format: Prometheus text exposition format\n")
                f.write(f"# Total unique metrics: {len(self.dynamic_metrics)}\n")
                f.write("# This shows the actual metrics that would be scraped by Prometheus\n")
                f.write("\n")
                f.write(metrics_text)

            LOG.info(f"Prometheus metrics debug output saved to: {filepath} ({len(self.dynamic_metrics)} unique metrics)")

        except Exception as e:
            LOG.error(f"Failed to write Prometheus debug metrics output: {e}")

    def close(self, timeout_seconds: int = 90, force_exit_on_timeout: bool = False) -> None:
        """Close the writer and clean up resources."""
        try:
            LOG.info("PrometheusWriter closing...")
            # Note: Prometheus HTTP server runs in background thread and will be cleaned up automatically
            LOG.info("PrometheusWriter closed successfully")
        except Exception as e:
            LOG.error(f"Error closing PrometheusWriter: {e}")
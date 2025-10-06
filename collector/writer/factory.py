"""
Writer factory for E-Series Performance Analyzer.
"""

import logging
import os
from typing import Optional

from .base import Writer
from .influxdb_writer import InfluxDBWriter
from .prometheus_writer import PrometheusWriter
from .multi_writer import MultiWriter

# Initialize logger
LOG = logging.getLogger(__name__)

class WriterFactory:
    """
    Factory for creating writer instances based on configuration.
    """

    @staticmethod
    def _get_debug_output_dir() -> Optional[str]:
        """
        Calculate debug output directory from COLLECTOR_LOG_FILE.
        Returns None if no valid debug directory available.
        """
        if os.getenv('COLLECTOR_LOG_LEVEL', '').upper() != 'DEBUG':
            return None

        collector_log_file = os.getenv('COLLECTOR_LOG_FILE', '')
        if not collector_log_file or collector_log_file == 'None':
            return None

        debug_dir = os.path.dirname(collector_log_file) if os.path.dirname(collector_log_file) else '.'
        if os.path.exists(debug_dir) and os.access(debug_dir, os.W_OK):
            return debug_dir

        LOG.warning(f"Debug output directory {debug_dir} not accessible")
        return None

    @staticmethod
    def create_writer_from_config(writer_config) -> Writer:
        """
        Create a writer based on WriterConfig object.

        This provides clean separation of concerns by accepting only
        writer-relevant configuration.

        Args:
            writer_config: WriterConfig instance with writer settings

        Returns:
            Appropriate Writer instance
        """
        output_choice = writer_config.output_format

        if output_choice == 'prometheus':
            LOG.info("Creating Prometheus writer from WriterConfig")
            debug_dir = WriterFactory._get_debug_output_dir()
            config = {
                'prometheus_port': writer_config.prometheus_port,
                'enable_json_output': debug_dir is not None,
                'enable_html_output': debug_dir is not None,
                'json_output_dir': debug_dir,
                'system_id': writer_config.system_id,
                'system_name': writer_config.system_name
            }
            return PrometheusWriter(config)

        elif output_choice == 'influxdb':
            LOG.info(f"Creating InfluxDB writer from WriterConfig with URL: {writer_config.influxdb_url}, database: {writer_config.influxdb_database}")
            debug_dir = WriterFactory._get_debug_output_dir()
            config = writer_config.to_dict()
            # InfluxDB writer expects specific field names and strict TLS validation
            config.update({
                'tls_validation': 'strict',  # InfluxDB always requires strict TLS validation
                'json_output_dir': debug_dir
            })
            return InfluxDBWriter(config)

        elif output_choice == 'both':
            writers = []

            # Add InfluxDB writer
            LOG.info(f"Creating InfluxDB writer for MultiWriter with URL: {writer_config.influxdb_url}, database: {writer_config.influxdb_database}")
            debug_dir = WriterFactory._get_debug_output_dir()
            influxdb_config = writer_config.to_dict()
            influxdb_config.update({
                'tls_validation': 'strict',  # InfluxDB always requires strict TLS validation
                'json_output_dir': debug_dir
            })
            influxdb_writer = InfluxDBWriter(influxdb_config)
            writers.append(influxdb_writer)
            LOG.info("Added InfluxDB writer to MultiWriter")

            # Add Prometheus writer
            debug_dir = WriterFactory._get_debug_output_dir()
            prometheus_config = {
                'prometheus_port': writer_config.prometheus_port,
                'enable_json_output': debug_dir is not None,
                'enable_html_output': debug_dir is not None,
                'json_output_dir': debug_dir,
                'system_id': writer_config.system_id,
                'system_name': writer_config.system_name
            }
            prometheus_writer = PrometheusWriter(prometheus_config)
            writers.append(prometheus_writer)
            LOG.info("Added Prometheus writer to MultiWriter")

            return MultiWriter(writers)

        else:
            LOG.error(f"Unknown output format: {output_choice}")
            raise ValueError(f"Unsupported output format: {output_choice}")
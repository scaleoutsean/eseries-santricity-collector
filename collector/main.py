"""Clean entry point for the new DataSource-based collector.

Provides same CLI interface as app/main.py for seamless transition.
"""

import argparse
import sys
import logging
from typing import Optional

from .core.collector import MetricsCollector
from .core.config import CollectorConfig
from .core.writer_config import WriterConfig
from .core.logging_config import LoggingConfigurator
from .utils import log_key_file_checksums


def create_argument_parser() -> argparse.ArgumentParser:
    """Create command line argument parser compatible with app/main.py."""

    parser = argparse.ArgumentParser(
        description='NetApp E-Series Performance Analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Live API collection to InfluxDB
  python -m collector --api 192.168.1.100 --username monitor --password secret \\
                      --influxdbUrl http://db.org.co:8181 --influxdbToken mytoken --influxDatabase epa

  # JSON replay mode
  python -m collector --fromJson ./data/samples/sample1 --systemId 6D039EA0004D00AA000000006652A086 \\
                      --influxdbUrl http://db.org.co:8181 --influxdbToken mytoken --influxDatabase epa
        """
    )

    # Data source selection (mutually exclusive)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--api', nargs='+', default=[],
                              help='List of E-Series API endpoints (IPv4 or IPv6 addresses or hostnames) to collect from')
    source_group.add_argument('--fromJson', type=str, default=None,
                              help='Directory to replay previously collected JSON metrics instead of live collection')

    # Authentication (required for live API)
    parser.add_argument('--username', '-u', type=str, default=None,
                        help='Username for SANtricity API authentication')
    parser.add_argument('--password', '-p', type=str, default=None,
                        help='Password for SANtricity API authentication')
    parser.add_argument('--tlsCa', type=str, default=None,
                        help='Path to CA certificate for verifying API/InfluxDB TLS connections (if not in system trust store).')
    parser.add_argument('--tlsValidation', type=str, choices=['strict', 'normal', 'none'], default='strict',
                        help='TLS validation mode for SANtricity API: strict (require valid CA and SKI/AKI), normal (default Python validation), none (disable all TLS validation). Default: strict.')

    # JSON replay options
    parser.add_argument('--systemId', type=str, default=None,
                        help='Filter JSON replay to specific system ID (WWN). Only used with --fromJson')

    # Output configuration
    output_group = parser.add_argument_group('Output Configuration')
    output_group.add_argument('--output', choices=['influxdb', 'prometheus', 'both'],
                              default='influxdb', help='Output format (default: influxdb)')

    # InfluxDB specific options
    influx_group = parser.add_argument_group('InfluxDB Configuration')
    influx_group.add_argument('--influxdbUrl', type=str, default=None,
                              help='InfluxDB server URL. Example: https://proxy.example.com:18181')
    influx_group.add_argument('--influxdbDatabase', type=str, default=None,
                              help='InfluxDB database name')
    influx_group.add_argument('--influxdbToken', type=str, default=None,
                              help='InfluxDB authentication token')

    # Prometheus specific options
    prometheus_group = parser.add_argument_group('Prometheus Configuration')
    prometheus_group.add_argument('--prometheus-port', type=int, default=8000,
                                  help='Prometheus metrics server port (default: 8000)')

    # Collection behavior
    behavior_group = parser.add_argument_group('Collection Behavior')
    behavior_group.add_argument('--intervalTime', type=int, default=60,
                                help='Collection interval in seconds. Allowed values: [60, 128, 180, 300] (default: 60)')
    behavior_group.add_argument('--no-events', dest='include_events', action='store_false',
                                help='Disable event data collection')
    behavior_group.add_argument('--no-environmental', dest='include_environmental', action='store_false',
                                help='Disable environmental monitoring collection')

    # Debugging
    debug_group = parser.add_argument_group('Debugging')
    debug_group.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                             default='INFO', help='Set logging level (default: INFO)')
    debug_group.add_argument('--logfile', type=str, default=None,
                             help='Path to log file (default: stdout only)')
    debug_group.add_argument('--maxIterations', type=int, default=0,
                             help='Maximum collection iterations (0=unlimited, >0=exit after N iterations)')

    return parser


def validate_arguments(args) -> Optional[str]:
    """Validate command line arguments.

    Returns:
        Error message if validation fails, None if valid
    """

    # Live API mode validation
    if args.api:
        if not args.username or not args.password:
            return "Username and password required for live API mode"

    # Interval validation - match old collector allowed values
    allowed_intervals = [60, 128, 180, 300]
    if args.intervalTime not in allowed_intervals:
        return f"--intervalTime must be one of {allowed_intervals} seconds"

    # InfluxDB validation (required if output includes influxdb)
    if args.output in ['influxdb', 'both']:
        required_influx = ['influxdbUrl', 'influxdbToken', 'influxdbDatabase']
        for field in required_influx:
            if not getattr(args, field):
                return f"--{field} required for InfluxDB output"

    # JSON replay validation
    if args.fromJson:
        if not args.systemId:
            return "System ID required for JSON replay mode (--systemId)"

    return None


def main():
    """Main entry point."""

    # Parse command line arguments
    parser = create_argument_parser()
    args = parser.parse_args()

    # Validate arguments
    error_msg = validate_arguments(args)
    if error_msg:
        parser.error(error_msg)

    try:
        # Create collector configuration
        config = CollectorConfig.from_args(args)

        # Setup logging using centralized configuration
        LoggingConfigurator.setup_logging(
            log_level=config.log_level,
            log_file=config.logfile
        )

        # Log file integrity info for debugging container staleness
        log_key_file_checksums()

        # Log startup configuration for debugging
        logging.info("=== E-Series Performance Analyzer Startup ===")
        logging.info(f"Data Source: {'JSON Replay' if args.fromJson else 'Live API'}")
        if args.fromJson:
            logging.info(f"JSON Directory: {args.fromJson}")
            logging.info(f"System ID Filter: {args.systemId}")
        else:
            logging.info(f"API Endpoints: {args.api}")
            logging.info(f"Username: {args.username}")
            logging.info(f"TLS Validation: {args.tlsValidation}")
            if args.tlsCa:
                logging.info(f"TLS CA Certificate: {args.tlsCa}")

        logging.info(f"Output Mode: {args.output}")
        logging.info(f"Collection Interval: {args.intervalTime}s")
        logging.info(f"Include Events: {args.include_events}")
        logging.info(f"Include Environmental: {args.include_environmental}")
        logging.info(f"Log Level: {config.log_level}")
        if config.logfile:
            logging.info(f"Log File: {config.logfile}")
        if args.maxIterations > 0:
            logging.info(f"Max Iterations: {args.maxIterations}")

        if args.output in ['influxdb', 'both']:
            logging.info(f"InfluxDB URL: {args.influxdbUrl}")
            logging.info(f"InfluxDB Database: {args.influxdbDatabase}")
            logging.info("InfluxDB Token: [REDACTED]")

        if args.output in ['prometheus', 'both']:
            logging.info(f"Prometheus Port: {args.prometheus_port}")
        logging.info("=== Configuration Complete ===")

        # Initialize collector with config only (no writer yet)
        collector = MetricsCollector(config, writer_config=None)

        # Initialize datasource to discover system info
        if not collector.initialize():
            logging.error("Failed to initialize collector datasource")
            sys.exit(1)

        # Get system info from initialized datasource
        sys_info = collector.datasource.get_system_info() if collector.datasource else None
        if not sys_info or not sys_info.wwn:
            logging.error("Failed to discover system identification. Cannot proceed without system WWN.")
            if args.fromJson:
                logging.error("Ensure --systemId matches available JSON files in directory")
            else:
                logging.error("Ensure API connection is working and system is accessible")
            sys.exit(1)

        logging.info(f"Discovered system: ID={sys_info.wwn}, Name={sys_info.name}")

        # Now create writer configuration with proper system info
        writer_config = WriterConfig.from_args(args, system_id=sys_info.wwn, system_name=sys_info.name)

        # Initialize writer with proper system identification
        collector.set_writer_config(writer_config)

        # Run collection
        logging.info("Starting E-Series collection...")
        collector.run_continuous()

    except KeyboardInterrupt:
        logging.info("Received interrupt, shutting down...")
    except Exception as e:
        logging.error(f"Collector error: {e}")
        if args.log_level == 'DEBUG':
            raise
        sys.exit(1)
if __name__ == '__main__':
    main()

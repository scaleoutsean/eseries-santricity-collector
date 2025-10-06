"""Core configuration classes for the collector."""

from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class CollectorConfig:
    """Main configuration for the collector system.

    Replaces complex argument passing from app/main.py with clean
    configuration object pattern.
    """

    # Data source configuration
    use_json_replay: bool = False
    from_json: Optional[str] = None
    system_id: Optional[str] = None  # WWN filter (was system_id_filter)

    # Live API configuration
    api: Optional[list] = None  # API endpoints (was management_ips)
    username: Optional[str] = None
    password: Optional[str] = None
    tls_ca: Optional[str] = None
    tls_validation: str = 'strict'  # 'strict', 'normal', 'none'

    # Output configuration
    output: str = 'both'  # 'influxdb', 'prometheus', or 'both'

    # Collection behavior
    interval_time: int = 60  # seconds between collections
    include_events: bool = True
    include_environmental: bool = True

    # Debugging
    debug: bool = False
    log_level: str = 'INFO'        # InfluxDB and Prometheus (each only if enabled) output can be saved but requires DEBUG
    logfile: Optional[str] = None  # Path to log file output effective if log_level=DEBUG

    # Collection control
    max_iterations: int = 0  # 0 = unlimited, >0 = exit after N iterations

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.use_json_replay:
            if not self.from_json:
                raise ValueError("from_json required for JSON replay mode")
        else:
            if not self.api or not self.username or not self.password:
                raise ValueError("api, username, password required for live API mode")

        # Allowed interval values (same as original collector)
        allowed_intervals = [60, 128, 180, 300]
        if self.interval_time not in allowed_intervals:
            raise ValueError(f"interval_time must be one of {allowed_intervals}")

    @classmethod
    def from_args(cls, args) -> 'CollectorConfig':
        """Create configuration from command line arguments.

        Compatible with existing app/main.py argument parsing.
        """
        return cls(
            use_json_replay=hasattr(args, 'fromJson') and args.fromJson is not None,
            from_json=getattr(args, 'fromJson', None),
            system_id=getattr(args, 'systemId', None),
            api=getattr(args, 'api', None),
            username=getattr(args, 'username', None),
            password=getattr(args, 'password', None),
            tls_ca=getattr(args, 'tlsCa', None),
            tls_validation=getattr(args, 'tlsValidation', 'strict'),
            output=getattr(args, 'output', 'both'),
            interval_time=getattr(args, 'intervalTime', 60),
            include_events=getattr(args, 'include_events', True),
            include_environmental=getattr(args, 'include_environmental', True),
            debug=getattr(args, 'debug', False),
            log_level=getattr(args, 'log_level', 'INFO'),
            logfile=getattr(args, 'logfile', None),
            max_iterations=getattr(args, 'maxIterations', 0)
        )

    @staticmethod
    def extract_writer_args(args) -> Dict[str, Any]:
        """Extract writer-specific arguments from command line args.

        Returns dictionary that can be used to create WriterConfig.
        """
        return {
            'output_format': getattr(args, 'output', 'influxdb'),
            'influxdb_url': getattr(args, 'influxdbUrl', None),
            'influxdb_token': getattr(args, 'influxdbToken', None),
            'influxdb_database': getattr(args, 'influxdbDatabase', None),
            'prometheus_port': getattr(args, 'prometheus_port', 8000)
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary for passing to DataSources."""
        return {
            'use_json_replay': self.use_json_replay,
            'from_json': self.from_json,
            'system_id': self.system_id,
            'api': self.api,
            'username': self.username,
            'password': self.password,
            'tls_ca': self.tls_ca,
            'tls_validation': self.tls_validation,
            'output': self.output,
            'interval_time': self.interval_time,
            'include_events': self.include_events,
            'include_environmental': self.include_environmental,
            'logfile': self.logfile,
            'max_iterations': self.max_iterations,
        }

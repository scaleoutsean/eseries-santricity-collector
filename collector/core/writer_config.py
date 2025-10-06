"""Writer configuration abstraction.

Separates writer-specific configuration from main collector config.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class WriterConfig:
    """Configuration specific to output writers.

    This keeps writer details out of the main collector configuration.
    """

    # General output configuration
    output_format: str = 'influxdb'  # 'influxdb', 'prometheus', 'both'

    # InfluxDB-specific configuration (only populated if needed)
    influxdb_url: Optional[str] = None
    influxdb_token: Optional[str] = None
    influxdb_database: Optional[str] = None

    # TLS configuration (for InfluxDB strict validation)
    tls_ca: Optional[str] = None

    # Prometheus-specific configuration (only populated if needed)
    prometheus_port: int = 8000

    # System identification (passed from collector)
    system_id: str = 'unknown'
    system_name: str = 'unknown'

    def __post_init__(self):
        """Validate writer configuration after initialization."""
        # InfluxDB validation - ensure required fields are present if InfluxDB output is enabled
        if self.output_format in ['influxdb', 'both']:
            required_fields = ['influxdb_url', 'influxdb_token', 'influxdb_database']
            for field in required_fields:
                value = getattr(self, field)
                if not value:
                    raise ValueError(f"{field} required for InfluxDB output (output_format={self.output_format})")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for writer initialization."""
        config: Dict[str, Any] = {
            'output_format': self.output_format,
            'system_id': self.system_id,
            'system_name': self.system_name,
        }

        # Only include InfluxDB config if InfluxDB output is enabled
        if self.output_format in ['influxdb', 'both']:
            influxdb_config: Dict[str, Any] = {
                'influxdb_url': self.influxdb_url,
                'influxdb_token': self.influxdb_token,
                'influxdb_database': self.influxdb_database,
                'tls_ca': self.tls_ca,  # Include TLS CA for InfluxDB strict validation
            }
            config.update(influxdb_config)

        # Only include Prometheus config if Prometheus output is enabled
        if self.output_format in ['prometheus', 'both']:
            prometheus_config: Dict[str, Any] = {
                'prometheus_port': self.prometheus_port,
            }
            config.update(prometheus_config)

        return config

    @classmethod
    def from_collector_config(cls, collector_config, system_id: str = 'unknown',
                            system_name: str = 'unknown') -> 'WriterConfig':
        """Create WriterConfig from main collector configuration.

        Args:
            collector_config: Main CollectorConfig instance
            system_id: System WWN (discovered at runtime)
            system_name: System name (discovered at runtime)

        Returns:
            WriterConfig with only writer-relevant settings
        """
        return cls(
            output_format=collector_config.output,
            tls_ca=collector_config.tls_ca,  # Pass TLS CA for InfluxDB strict validation
            prometheus_port=8000,  # Default
            system_id=system_id,
            system_name=system_name
        )

    @classmethod
    def from_args(cls, args, system_id: str = 'unknown',
                 system_name: str = 'unknown') -> 'WriterConfig':
        """Create WriterConfig directly from command line arguments.

        Args:
            args: Parsed command line arguments
            system_id: System WWN (discovered at runtime or from JSON replay)
            system_name: System name (discovered at runtime or from JSON replay)

        Returns:
            WriterConfig with writer-relevant settings extracted from args
        """
        # For JSON replay mode, extract system_id from --systemId provided and confirm in extraction
        # But only if system_id wasn't already discovered (backward compatibility)
        if (hasattr(args, 'fromJson') and args.fromJson and
            hasattr(args, 'systemId') and args.systemId and
            system_id == 'unknown'):
            system_id = args.systemId

        return cls(
            output_format=getattr(args, 'output', 'influxdb'),
            influxdb_url=getattr(args, 'influxdbUrl', None),
            influxdb_token=getattr(args, 'influxdbToken', None),
            influxdb_database=getattr(args, 'influxdbDatabase', None),
            tls_ca=getattr(args, 'tlsCa', None),  # Extract TLS CA for InfluxDB strict validation
            prometheus_port=getattr(args, 'prometheus_port', 8000),
            system_id=system_id,
            system_name=system_name
        )

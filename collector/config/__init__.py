"""
Configuration management for E-Series Performance Analyzer.
"""

import os
import yaml
import json
from typing import List, Optional, Dict, Any
import logging

# Initialize logger
LOG = logging.getLogger(__name__)

# Default InfluxDB write precision
INFLUXDB_WRITE_PRECISION = "s"

class Settings:
    """
    Configuration settings for the E-Series Performance Analyzer.
    Supports loading from environment variables, YAML, or JSON.
    """

    def __init__(self, config_file: Optional[str] = None, from_env: bool = True):
        """
        Initialize settings from a config file or environment variables.

        Args:
            config_file: Path to YAML or JSON configuration file
            from_env: Whether to load settings from environment variables
        """
        # Default values
        self.api: List[str] = []
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.influxdb_url: Optional[str] = None
        self.influxdb_database: Optional[str] = None
        self.influxdb_token: Optional[str] = None
        self.tls_ca: Optional[str] = None

        # Load configuration in order of precedence
        if config_file:
            self._load_from_file(config_file)

        if from_env:
            self._load_from_env()

    def _load_from_file(self, config_file: str) -> None:
        """Load settings from a YAML or JSON file."""
        try:
            if not os.path.exists(config_file):
                LOG.warning(f"Config file not found: {config_file}")
                return

            with open(config_file, 'r', encoding='utf-8') as f:
                if config_file.lower().endswith('.yaml') or config_file.lower().endswith('.yml'):
                    config = yaml.safe_load(f)
                elif config_file.lower().endswith('.json'):
                    config = json.load(f)
                else:
                    LOG.warning(f"Unsupported config file format: {config_file}")
                    return

                # Apply configuration settings
                self.api = config.get('api_endpoints', [])
                self.username = config.get('username')
                self.password = config.get('password')
                self.influxdb_url = config.get('influxdb_url')
                self.influxdb_database = config.get('influxdb_database')
                self.influxdb_token = config.get('influxdb_token')
                self.tls_ca = config.get('tls_ca')

                LOG.info(f"Loaded configuration from {config_file}")

        except Exception as e:
            LOG.error(f"Failed to load config from {config_file}: {e}")

    def _load_from_env(self) -> None:
        """Load settings from environment variables."""
        # API Configuration - use actual env vars from .env and docker-compose
        if os.getenv('API'):
            # API can be space-separated list like "2.2.2.2 3.3.3.3"
            self.api = os.getenv('API', '').split()

        self.username = os.getenv('SANTRICITY_USERNAME', self.username)
        self.password = os.getenv('SANTRICITY_PASSWORD', self.password)

        # InfluxDB Configuration
        self.influxdb_url = os.getenv('INFLUXDB_URL', self.influxdb_url)
        self.influxdb_database = os.getenv('INFLUXDB_DATABASE', self.influxdb_database)
        self.influxdb_token = os.getenv('INFLUXDB_TOKEN', self.influxdb_token)

        # TLS Configuration
        self.tls_ca = os.getenv('TLS_CA', self.tls_ca)

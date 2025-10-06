"""Centralized logging configuration for the collector.

Provides clean separation between configuration parsing and logging setup.
"""

import logging
import os
from typing import Optional


class LoggingConfigurator:
    """Handles all logging setup independently of other configuration."""

    @staticmethod
    def setup_logging(log_level: str = 'INFO', log_file: Optional[str] = None) -> None:
        """Set up logging configuration. Use DEBUG for InfluxDB and Prometheus output checkpointing.

        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
            log_file: Optional path to log file. If None, logs to console only.
        """
        level = getattr(logging, log_level.upper())

        # Configure logging with file output if specified
        if log_file:
            # Ensure directory exists
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            # Configure file + console logging
            logging.basicConfig(
                level=level,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(log_file),
                    logging.StreamHandler()  # Also keep console output
                ]
            )
        else:
            # Console logging only
            logging.basicConfig(
                level=level,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """Get a logger instance.

        Args:
            name: Logger name (usually __name__)

        Returns:
            Configured logger instance
        """
        return logging.getLogger(name)

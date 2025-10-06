"""Core collector package initialization."""

from .collector import MetricsCollector
from .config import CollectorConfig

__all__ = ['MetricsCollector', 'CollectorConfig']
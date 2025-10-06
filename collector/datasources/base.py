"""Base DataSource interface and shared data structures."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import Enum


class CollectionType(Enum):
    """Types of data that can be collected."""
    PERFORMANCE = "performance"
    CONFIGURATION = "configuration"
    EVENTS = "events"
    ENVIRONMENTAL = "environmental"


@dataclass
class CollectionResult:
    """Result from a data collection operation."""
    collection_type: CollectionType
    data: Dict[str, List[Any]]
    success: bool
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class SystemInfo:
    """System identification information."""
    wwn: str
    name: str


class DataSource(ABC):
    """Abstract base class for all data sources.

    This interface eliminates the dual-path maintenance burden by providing
    a unified collection interface that works identically for both live API
    and JSON replay modes.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._system_info: Optional[SystemInfo] = None

    @property
    def system_info(self) -> Optional[SystemInfo]:
        """Get system information if available."""
        return self._system_info

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the data source. Returns True on success."""
        pass

    @abstractmethod
    def collect_performance_data(self) -> CollectionResult:
        """Collect all performance data types."""
        pass

    @abstractmethod
    def collect_configuration_data(self) -> CollectionResult:
        """Collect all configuration data types."""
        pass

    @abstractmethod
    def collect_event_data(self) -> CollectionResult:
        """Collect all event/alert data types."""
        pass

    @abstractmethod
    def collect_environmental_data(self) -> CollectionResult:
        """Collect environmental monitoring data (power, temperature)."""
        pass

    def get_system_info(self) -> Optional[SystemInfo]:
        """Get system information.

        Returns:
            SystemInfo if available, None otherwise
        """
        return getattr(self, '_system_info', None)

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up any resources used by the data source."""
        pass

    def advance_batch(self) -> bool:
        """Advance to the next batch (JSON replay only).

        Returns:
            True if batch advanced successfully, False if no more batches

        Note:
            Only implemented for JSON replay datasources.
            Live API datasources should return False.
        """
        return False

    def has_more_batches(self) -> bool:
        """Check if more batches are available (JSON replay only).

        Returns:
            True if more batches available, False otherwise

        Note:
            Only implemented for JSON replay datasources.
            Live API datasources should return False.
        """
        return False

    def collect_all_data(self) -> Dict[CollectionType, CollectionResult]:
        """Convenience method to collect all data types."""
        return {
            CollectionType.PERFORMANCE: self.collect_performance_data(),
            CollectionType.CONFIGURATION: self.collect_configuration_data(),
            CollectionType.EVENTS: self.collect_event_data(),
            CollectionType.ENVIRONMENTAL: self.collect_environmental_data()
        }
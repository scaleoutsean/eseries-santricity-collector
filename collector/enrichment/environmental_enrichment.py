"""
Environmental Data Enrichment for E-Series Performance Analyzer

This module enriches environmental monitoring data (power, temperature) with:
- System metadata (storage_system_id, storage_system_name)
- Data cleanup for temperature sensors (status vs actual temperature)
- Power data normalization and metadata injection

Environmental data from E-Series APIs comes without system identification,
requiring enrichment to add contextual metadata for proper storage and visualization.
"""

import logging
from typing import List, Dict, Any, Optional
from .system_identification_helper import SystemIdentificationHelper

LOG = logging.getLogger(__name__)

class EnvironmentalPowerEnrichment:
    """
    Enrichment processor for environmental power data.

    Adds system metadata and normalizes power consumption data structure.
    Raw power data lacks system identification - this enrichment adds it.
    """

    def __init__(self, system_enricher=None):
        """Initialize environmental power enricher."""
        self.system_enricher = system_enricher
        self.system_identifier = SystemIdentificationHelper(system_enricher)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def enrich_power_data(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enrich power/battery data with system metadata.

        Args:
            data: List of power/battery records from API

        Returns:
            List of enriched power records with system metadata
        """
        if not data:
            return data

        enriched_records = []

        for record in data:
            if not isinstance(record, dict):
                continue

            enriched_record = record.copy()

            # Get system configuration for this environmental data
            system_config = self.system_identifier.get_system_config_for_performance_data(record)
            if system_config:
                system_id = system_config.get('wwn')
                system_name = system_config.get('name')
            else:
                # Environmental data without system context - skip or fail based on requirements
                self.logger.warning("No system config found for environmental power data")
                system_id = None
                system_name = None

            # Add system metadata (missing from raw API data)
            enriched_record['storage_system_id'] = system_id
            enriched_record['storage_system_name'] = system_name

            enriched_records.append(enriched_record)

        return enriched_records


class EnvironmentalTemperatureEnrichment:
    """
    Enrichment processor for environmental temperature data.

    Handles two critical issues:
    1. Adds system metadata (missing from raw API data)
    2. Separates status sensors from temperature sensors (data cleanup)

    Raw temperature data contains mixed sensor types:
    - Status sensors: currentTemp=128 (OK), !=128 (NG) → sensor_status: 0 (OK), 1 (Error)
    - Temperature sensors: currentTemp=actual temperature in Celsius

    Note: Uses standard convention where sensor_status=0 means OK, sensor_status=1 means Error.
    """

    def __init__(self, system_enricher=None):
        """Initialize environmental temperature enricher."""
        self.system_enricher = system_enricher
        self.system_identifier = SystemIdentificationHelper(system_enricher)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def enrich(self, data: List[Dict[str, Any]], system_info: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        # Enrich environmental temperature data with system metadata and sensor type classification.

        Args:
            data: List of environmental temperature records
            system_info: System information for metadata injection

        Returns:
            List of enriched temperature records with proper sensor classification
        """
        if not data:
            return data

        enriched_records = []

        for record in data:
            if not isinstance(record, dict):
                continue

            enriched_record = record.copy()

            # Get system configuration for this environmental data
            system_config = self.system_identifier.get_system_config_for_performance_data(record)
            if system_config:
                system_id = system_config.get('wwn')
                system_name = system_config.get('name')
            else:
                self.logger.warning("No system config found for environmental temperature data")
                system_id = None
                system_name = None

            # Add system metadata (missing from raw API data)
            enriched_record['storage_system_id'] = system_id
            enriched_record['storage_system_name'] = system_name

            # Handle temperature sensor vs status sensor classification
            current_temp = record.get('currentTemp')
            sensor_ref = record.get('thermalSensorRef', 'unknown')

            if current_temp is not None:
                if self._is_status_sensor(current_temp, sensor_ref):
                    # Status sensor: currentTemp=128 (OK), !=128 (NG)
                    # Follow standard convention: 0=OK, 1=Error
                    enriched_record['sensor_type'] = 'status'
                    enriched_record['sensor_status'] = 0 if current_temp == 128 else 1  # 0=OK, 1=Error
                    enriched_record['sensor_status_text'] = 'OK' if current_temp == 128 else 'NG'
                    # Remove misleading temperature field
                    if 'currentTemp' in enriched_record:
                        del enriched_record['currentTemp']
                    self.logger.debug(f"Classified status sensor {sensor_ref}: status={enriched_record['sensor_status']} ({'OK' if enriched_record['sensor_status'] == 0 else 'NG'})")
                else:
                    # Real temperature sensor
                    enriched_record['sensor_type'] = 'temperature'
                    enriched_record['temperature_celsius'] = float(current_temp)
                    # Keep currentTemp for backward compatibility, but add semantic field
                    self.logger.debug(f"Classified temperature sensor {sensor_ref}: temp={current_temp}°C")
            else:
                # No temperature data
                enriched_record['sensor_type'] = 'unknown'
                self.logger.warning(f"Sensor {sensor_ref} has no currentTemp data")

            # Add enrichment timestamp
            enriched_record['enriched_at'] = 'environmental_temperature'

            enriched_records.append(enriched_record)

        status_count = sum(1 for r in enriched_records if r.get('sensor_type') == 'status')
        temp_count = sum(1 for r in enriched_records if r.get('sensor_type') == 'temperature')
        self.logger.info(f"Enriched {len(enriched_records)} temperature records: {temp_count} temperature sensors, {status_count} status sensors")

        return enriched_records

    def _is_status_sensor(self, temp_value: float, sensor_ref: str) -> bool:
        """
        Determine if a sensor is a status sensor based on temperature value and sensor reference.

        Status sensors typically:
        - Have currentTemp=128 for OK status
        - Have sensor references ending in '000001' (pattern observed)
        - Have non-realistic temperature values for status codes

        Args:
            temp_value: The currentTemp value from the sensor
            sensor_ref: The thermalSensorRef identifier

        Returns:
            True if this appears to be a status sensor, False if it's a temperature sensor
        """
        # Primary indicator: temp value of 128 is the OK status code
        if temp_value == 128:
            return True

        # Secondary indicator: sensor reference pattern (if we discover more patterns)
        if sensor_ref.endswith('000001'):
            return True

        # Temperature sensors should have realistic values (typically -40°C to 100°C for storage)
        # Values outside this range are likely status codes
        if temp_value < -40 or temp_value > 100:
            return True

        return False
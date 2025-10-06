"""Data extraction utilities for NetApp E-Series API responses.

Handles the various data structure formats returned by different API endpoints
and file formats to provide consistent data extraction for both JSON replay
and Live API modes.
"""

import logging
from typing import Dict, List, Any, Optional


logger = logging.getLogger(__name__)


def extract_analyzed_statistics_data(
    response_data: Any,
    endpoint_key: str,
    source_type: str = "unknown",
    auto_inject_system_context: bool = True
) -> List[Dict[str, Any]]:
    """Extract analyzed statistics data from various API response formats.

    Handles the 3 different analyzed statistics formats:
    1. System statistics: Single object under .data (analysed_system_statistics)
    2. Controller statistics: Array under .data.statistics (analyzed_controller_statistics)
    3. Volume/Drive/Interface statistics: Direct array under .data (analysed_*_statistics)

    Args:
        response_data: Raw response data from API or JSON file
        endpoint_key: The endpoint identifier (e.g., 'analyzed_system_statistics')
        source_type: Source identifier for logging ('json_replay', 'live_api', etc.)
        auto_inject_system_context: Whether to automatically inject unified system context

    Returns:
        List of dictionaries containing the extracted statistics records with system context
    """

    # Handle different input structures based on source
    if isinstance(response_data, dict):
        # Check for wrapped JSON file format: {"system_id": "...", "data": ...}
        if 'data' in response_data and 'system_id' in response_data:
            # JSON file wrapper format
            actual_data = response_data['data']
            logger.debug(f"[{source_type}] Extracted data from JSON file wrapper for {endpoint_key}")
        elif 'statistics' in response_data:
            # Live API format for analyzed statistics: {"statistics": [...]}
            actual_data = {'statistics': response_data['statistics']}
            logger.debug(f"[{source_type}] Found Live API statistics wrapper for {endpoint_key}")
        else:
            # Direct data or other format
            actual_data = response_data
            logger.debug(f"[{source_type}] Using direct response data for {endpoint_key}")
    else:
        # Direct array or other non-dict format
        actual_data = response_data
        logger.debug(f"[{source_type}] Using non-dict response data for {endpoint_key}")

    # Now extract based on endpoint type and data structure
    extracted_records = []

    if endpoint_key == 'analyzed_system_statistics':
        # System statistics: Single object under .data
        if isinstance(actual_data, dict):
            if 'statistics' in actual_data:
                # Some formats might wrap system stats too
                sys_data = actual_data['statistics']
                if isinstance(sys_data, list) and len(sys_data) > 0:
                    extracted_records = [sys_data[0]]  # Take first system record
                elif isinstance(sys_data, dict):
                    extracted_records = [sys_data]
            else:
                # Direct system object
                extracted_records = [actual_data]
        elif isinstance(actual_data, list) and len(actual_data) > 0:
            # Already a list, take first item
            extracted_records = [actual_data[0]]

    elif endpoint_key == 'analyzed_controller_statistics':
        # Controller statistics: Array under .data.statistics
        if isinstance(actual_data, dict) and 'statistics' in actual_data:
            controller_stats = actual_data['statistics']
            if isinstance(controller_stats, list):
                extracted_records = controller_stats
            elif controller_stats:
                extracted_records = [controller_stats]
        elif isinstance(actual_data, list):
            # Direct array format
            extracted_records = actual_data
        elif isinstance(actual_data, dict):
            # Single controller record
            extracted_records = [actual_data]

    else:
        # Volume/Drive/Interface statistics: Direct array under .data
        if isinstance(actual_data, dict) and 'statistics' in actual_data:
            # Handle potential statistics wrapper
            stats_data = actual_data['statistics']
            if isinstance(stats_data, list):
                extracted_records = stats_data
            elif stats_data:
                extracted_records = [stats_data]
        elif isinstance(actual_data, list):
            # Direct array format (most common for volume/drive/interface)
            extracted_records = actual_data
        elif isinstance(actual_data, dict):
            # Single record
            extracted_records = [actual_data]

    # Ensure we always return a list
    if not isinstance(extracted_records, list):
        extracted_records = [extracted_records] if extracted_records else []

    # Filter out None values
    extracted_records = [record for record in extracted_records if record is not None]

    # Inject unified system context into each extracted record
    if auto_inject_system_context and extracted_records:
        from .system_context import system_context_manager
        system_context_manager.inject_system_context(extracted_records)

    logger.debug(f"[{source_type}] Extracted {len(extracted_records)} records for {endpoint_key}")

    return extracted_records


def extract_configuration_data(
    response_data: Any,
    endpoint_key: str,
    source_type: str = "unknown",
    auto_inject_system_context: bool = True
) -> List[Dict[str, Any]]:
    """Extract configuration data from various API response formats.

    Handles both old and new JSON formats:
    - Old format (raw collector): Direct JSON objects/arrays
    - New format (centralized): Wrapped with metadata {"data": ..., "system_id": ...}

    Configuration endpoints can return:
    - Single objects (system_config)
    - Arrays of objects (volumes, drives, etc.)
    - Wrapped responses with metadata

    Args:
        response_data: Raw response data from API or JSON file
        endpoint_key: The endpoint identifier (e.g., 'system_config')
        source_type: Source identifier for logging
        auto_inject_system_context: Whether to automatically inject unified system context

    Returns:
        List of dictionaries containing the extracted configuration records with system context
    """

    # Handle wrapped JSON file format first (new format)
    if isinstance(response_data, dict) and 'data' in response_data and 'system_id' in response_data:
        actual_data = response_data['data']
        logger.debug(f"[{source_type}] Extracted data from NEW JSON file wrapper for {endpoint_key}")
    elif isinstance(response_data, dict) and len(response_data) > 0:
        # Check if this looks like old format (has fields like 'name', 'wwn', etc. directly)
        has_direct_fields = any(field in response_data for field in ['name', 'wwn', 'id', 'label', 'controllerId', 'interfaceRef'])
        if has_direct_fields:
            actual_data = response_data
            logger.debug(f"[{source_type}] Using OLD format direct data for {endpoint_key}")
        else:
            actual_data = response_data
            logger.debug(f"[{source_type}] Using response data as-is for {endpoint_key}")
    else:
        actual_data = response_data

    # Extract configuration records
    if isinstance(actual_data, list):
        # Direct array of configuration records
        config_records = actual_data
    elif isinstance(actual_data, dict):
        # Single configuration object - wrap in list for consistency
        config_records = [actual_data]
    else:
        # Fallback for other formats
        config_records = [actual_data] if actual_data else []

    # Filter out None values
    config_records = [record for record in config_records if record is not None]

    # Inject unified system context into each extracted record
    if auto_inject_system_context and config_records:
        from .system_context import system_context_manager
        system_context_manager.inject_system_context(config_records)

    logger.debug(f"[{source_type}] Extracted {len(config_records)} configuration records for {endpoint_key}")

    return config_records


def extract_system_name_from_config(config_data: Any) -> Optional[str]:
    """Extract system name from system configuration data.

    Note: JSON files are automatically normalized by JsonReader to remove
    raw_collector wrapper, so this function only needs to handle direct format.

    Args:
        config_data: System configuration data (normalized format)

    Returns:
        System name if found, None otherwise
    """

    if not config_data:
        return None

    # Handle direct format (now standardized across Live API and JSON replay)
    if isinstance(config_data, dict):
        return config_data.get('name')
    elif isinstance(config_data, list) and len(config_data) > 0:
        first_item = config_data[0]
        if isinstance(first_item, dict):
            return first_item.get('name')

    return None
#!/usr/bin/env python3
"""
API Endpoint Categorization for E-Series Performance Analyzer

This module categorizes E-Series API endpoints into three main types:
- PERFORMANCE: Real-time metrics and statistics
- CONFIGURATION: Static/semi-static system configuration
- EVENTS: Dynamic status, jobs, alerts, and transient events

Each category has different collection patterns and storage requirements.
"""

from enum import Enum
from typing import Dict, List, Set, Any

class EndpointCategory(Enum):
    """Categories for API endpoint collection"""
    PERFORMANCE = "performance"     # Real-time metrics, always collected
    CONFIGURATION = "configuration" # Static config, cached and collected per schedule
    EVENTS = "events"               # Dynamic status/jobs, immediate write to DB
    ENVIRONMENTAL = "environmental" # Environmental monitoring (power, temperature)

# Endpoint categorization based on tools/collect_items.py
ENDPOINT_CATEGORIES = {

    # PERFORMANCE: Real-time metrics and statistics
    EndpointCategory.PERFORMANCE: {
        'analyzed_volume_statistics',
        'analyzed_drive_statistics',
        'analyzed_system_statistics',
        'analyzed_interface_statistics',
        'analyzed_controller_statistics',

        # Aggregate data keys from main collection
        'performance_data',
        'total_records',
        'status',
    },

    # CONFIGURATION: Static/semi-static system configuration
    EndpointCategory.CONFIGURATION: {
        # System-level configuration
        'system_config',
        'controller_config',
        'tray_config',
        'ethernet_interface_config',
        'interfaces_config',

        # Storage configuration
        'storage_pools',
        'volumes_config',
        'volume_mappings_config',
        'drive_config',
        'ssd_cache',

        # Host connectivity
        'hosts',
        'host_groups',

        # Advanced storage features
        'snapshot_schedules',
        'snapshot_groups',
        'snapshot_volumes',
        'snapshot_images',
        'mirrors',
        'async_mirrors',
        'volume_consistency_group_config',
        'volume_consistency_group_members',

        # ID-dependent configuration endpoints
        'snapshot_groups_repository_utilization',
        'volume_expansion_progress',
    },

    # EVENTS: Dynamic status, jobs, alerts, and transient events
    EndpointCategory.EVENTS: {
        # System status and events
        'system_failures',
        'lockdown_status',

        # Job status and progress
        'volume_parity_check_status',
        'volume_parity_job_check_errors',
        'data_parity_scan_job_status',
        'parity_scan_jobs',
        'volume_copy_jobs',
        'volume_copy_job_progress',
        'drives_erase_progress',
        'storage_pools_action_progress',
        'volume_expansion_progress',

        # Alert and failure information
        # Note: Add more event-type endpoints here as discovered
    },

    # ENVIRONMENTAL: Environmental monitoring (power, temperature)
    EndpointCategory.ENVIRONMENTAL: {
        # Environmental monitoring (Symbol API) - operational time-series metrics
        'env_power',
        'env_temperature',
    }
}

def get_endpoint_category(endpoint_name: str) -> EndpointCategory:
    """
    Get the category for a given endpoint name

    Args:
        endpoint_name: Name of the API endpoint

    Returns:
        EndpointCategory enum value

    Raises:
        ValueError: If endpoint is not categorized
    """
    for category, endpoints in ENDPOINT_CATEGORIES.items():
        if endpoint_name in endpoints:
            return category

    raise ValueError(f"Endpoint '{endpoint_name}' is not categorized")

def get_endpoints_by_category(category: EndpointCategory) -> Set[str]:
    """
    Get all endpoints for a specific category

    Args:
        category: The endpoint category

    Returns:
        Set of endpoint names in that category
    """
    return ENDPOINT_CATEGORIES.get(category, set())

def get_all_categorized_endpoints() -> Set[str]:
    """
    Get all endpoints that have been categorized

    Returns:
        Set of all categorized endpoint names
    """
    all_endpoints = set()
    for endpoints in ENDPOINT_CATEGORIES.values():
        all_endpoints.update(endpoints)
    return all_endpoints

def validate_endpoint_coverage(all_known_endpoints: Set[str]) -> Dict[str, List[str]]:
    """
    Validate that all known endpoints are categorized

    Args:
        all_known_endpoints: Set of all endpoints that should be categorized

    Returns:
        Dictionary with 'categorized' and 'uncategorized' lists
    """
    categorized = get_all_categorized_endpoints()
    uncategorized = all_known_endpoints - categorized

    return {
        'categorized': sorted(list(categorized)),
        'uncategorized': sorted(list(uncategorized))
    }

# Collection behavior definitions
COLLECTION_BEHAVIORS = {
    EndpointCategory.PERFORMANCE: {
        'typical_frequency': 'FREQUENT_REFRESH',  # Every 5 minutes
        'write_immediately': True,     # Write to DB immediately
        'cache_data': False,           # Don't cache performance data
        'use_scheduler': False,        # Always collect (no scheduling)
        'export_prometheus': True,     # Export via Prometheus
        'enable_enrichment': True,     # Performance data is always enriched
        'enrichment_type': 'performance',  # Use performance enrichment pipeline
    },

    EndpointCategory.CONFIGURATION: {
        'typical_frequency': 'STANDARD_REFRESH',  # Every 10 minutes
        'write_immediately': False,    # Cache and write periodically
        'cache_data': True,            # Cache config data for enrichment
        'use_scheduler': True,         # Use scheduling system
        'export_prometheus': False,    # Don't export via Prometheus (too static)
    },

    EndpointCategory.EVENTS: {
        'typical_frequency': 'FREQUENT_REFRESH',  # Check every 5 minutes
        'write_immediately': True,     # Write to DB immediately when data exists
        'cache_data': False,           # Don't cache event data
        'use_scheduler': False,        # Check frequently, write only when data exists
        'export_prometheus': True,     # Export important events (system failures, lockdown) to Prometheus
        'write_only_when_data': True,  # Only write when response is not empty
        'enable_enrichment': True,     # Enable event enrichment for alerting
        'enrichment_type': 'event',    # Use event enrichment pipeline
        'enable_deduplication': True,  # Enable event deduplication
        'dedup_window_minutes': 5,     # Deduplication window in minutes
        'enable_grafana_annotations': False,  # Optional Grafana annotation integration
    },

    EndpointCategory.ENVIRONMENTAL: {
        'typical_frequency': 'FREQUENT_REFRESH',  # Every 5 minutes (like performance)
        'write_immediately': True,     # Write to DB immediately
        'cache_data': False,           # Don't cache environmental data
        'use_scheduler': False,        # Always collect (no scheduling)
        'export_prometheus': True,     # Export via Prometheus (important for monitoring)
        'enable_enrichment': True,     # Environmental data needs enrichment (power/temp processing)
        'enrichment_type': 'environmental',  # Use environmental enrichment pipeline
    }
}

def get_collection_behavior(category: EndpointCategory) -> Dict[str, Any]:
    """
    Get the collection behavior configuration for a category

    Args:
        category: The endpoint category

    Returns:
        Dictionary with collection behavior settings
    """
    return COLLECTION_BEHAVIORS.get(category, {})

# Centralized endpoint to measurement name mapping
# This is the SINGLE SOURCE OF TRUTH for all API endpoint -> measurement name transformations
# Eliminates ad-hoc string replacement logic throughout the codebase
ENDPOINT_TO_MEASUREMENT_MAPPING = {
    # Event endpoints (API names -> internal measurement names)
    'system_failures': 'events_system_failures',
    'lockdown_status': 'events_lockdown_status',
    'parity_scan_jobs': 'events_parity_scan_jobs',
    'volume_copy_jobs': 'events_volume_copy_jobs',
    'volume_parity_check_status': 'events_volume_parity_check_status',
    'volume_parity_job_check_errors': 'events_volume_parity_job_check_errors',
    'data_parity_scan_job_status': 'events_data_parity_scan_job_status',
    'volume_copy_job_progress': 'events_volume_copy_job_progress',
    'drives_erase_progress': 'events_drives_erase_progress',
    'storage_pools_action_progress': 'events_storage_pools_action_progress',
    'volume_expansion_progress': 'events_volume_expansion_progress',

    # Performance endpoints (API names -> internal measurement names)
    'analyzed_volume_statistics': 'performance_volume_statistics',
    'analyzed_drive_statistics': 'performance_drive_statistics',
    'analyzed_system_statistics': 'performance_system_statistics',
    'analyzed_interface_statistics': 'performance_interface_statistics',
    'analyzed_controller_statistics': 'performance_controller_statistics',

    # Environmental endpoints (already correctly named)
    'env_power': 'env_power',
    'env_temperature': 'env_temperature',

    # Configuration endpoints (API names -> clean config_<object> measurement names)
    'system_config': 'config_system',
    'controller_config': 'config_controller',
    'tray_config': 'config_tray',
    'ethernet_interface_config': 'config_ethernet_interface',
    'interfaces_config': 'config_interfaces',
    'storage_pools': 'config_storage_pools',
    'volumes_config': 'config_volumes',
    'volume_mappings_config': 'config_volume_mappings',
    'drive_config': 'config_drives',
    'hosts': 'config_hosts',
    'host_groups': 'config_host_groups',
    'snapshot_images': 'config_snapshots',
    'snapshot_groups': 'config_snapshot_groups',
    'snapshot_schedules': 'config_snapshot_schedules',
}

def get_measurement_name(endpoint_name: str) -> str:
    """
    Get the canonical measurement name for an API endpoint

    Args:
        endpoint_name: API endpoint name

    Returns:
        Canonical measurement name for internal processing and storage
    """
    return ENDPOINT_TO_MEASUREMENT_MAPPING.get(endpoint_name, endpoint_name)

def get_endpoint_from_measurement(measurement_name: str) -> str:
    """
    Reverse lookup: get API endpoint name from measurement name

    Args:
        measurement_name: Internal measurement name

    Returns:
        Original API endpoint name, or measurement_name if no mapping exists
    """
    # Create reverse mapping
    reverse_mapping = {v: k for k, v in ENDPOINT_TO_MEASUREMENT_MAPPING.items()}
    return reverse_mapping.get(measurement_name, measurement_name)

# Enrichment processor mapping for reference
# This documents which enrichment processors handle which endpoints
ENRICHMENT_PROCESSOR_MAPPING = {
    # Performance endpoints -> specific enrichment processors
    'analyzed_volume_statistics': 'VolumeEnrichmentProcessor',
    'analyzed_drive_statistics': 'DriveEnrichmentProcessor',
    'analyzed_system_statistics': 'SystemEnrichmentProcessor',
    'analyzed_interface_statistics': 'ControllerEnrichmentProcessor',
    'analyzed_controller_statistics': 'ControllerEnrichmentProcessor',

    # Environmental monitoring endpoints -> proper enrichment processors (not passthrough!)
    'env_power': 'EnvironmentalPowerEnrichment',
    'env_temperature': 'EnvironmentalTemperatureEnrichment',

    # Event endpoints -> event enrichment processor
    'system_failures': 'EventEnrichment',
    'lockdown_status': 'EventEnrichment',
    'volume_parity_check_status': 'EventEnrichment',
    'parity_scan_jobs': 'EventEnrichment',
    'volume_copy_jobs': 'EventEnrichment',
    # ... other event endpoints use EventEnrichment
}

def get_enrichment_processor(endpoint_name: str) -> str:
    """
    Get the enrichment processor class name for a given endpoint

    Args:
        endpoint_name: Name of the API endpoint

    Returns:
        Name of the enrichment processor class

    Raises:
        ValueError: If no enrichment processor is defined for the endpoint
    """
    processor = ENRICHMENT_PROCESSOR_MAPPING.get(endpoint_name)
    if not processor:
        # Check category-level enrichment
        try:
            category = get_endpoint_category(endpoint_name)
            behavior = get_collection_behavior(category)
            if behavior.get('enable_enrichment'):
                enrichment_type = behavior.get('enrichment_type', 'unknown')
                return f"{enrichment_type.title()}Enrichment"
        except ValueError:
            pass

        raise ValueError(f"No enrichment processor defined for endpoint '{endpoint_name}'")

    return processor

def should_export_to_prometheus(endpoint_or_measurement_name: str) -> bool:
    """
    Determine if an endpoint/measurement should be exported to Prometheus using centralized categorization.

    This function handles both API endpoint names and internal measurement names by using
    the centralized ENDPOINT_TO_MEASUREMENT_MAPPING for consistent routing decisions.

    Args:
        endpoint_or_measurement_name: API endpoint name OR internal measurement name

    Returns:
        bool: True if should be exported to Prometheus
    """
    # Try direct endpoint lookup first
    try:
        category = get_endpoint_category(endpoint_or_measurement_name)
        behavior = get_collection_behavior(category)
        return behavior.get('export_prometheus', False)
    except ValueError:
        pass

    # Try reverse lookup from measurement name to endpoint name
    endpoint_name = get_endpoint_from_measurement(endpoint_or_measurement_name)
    if endpoint_name != endpoint_or_measurement_name:
        try:
            category = get_endpoint_category(endpoint_name)
            behavior = get_collection_behavior(category)
            return behavior.get('export_prometheus', False)
        except ValueError:
            pass

    # Special handling for direct measurement names that map to categorized endpoints
    # This handles cases like 'events_system_failures' which should export to Prometheus
    # because the underlying 'system_failures' endpoint is in EVENTS category
    for endpoint, measurement in ENDPOINT_TO_MEASUREMENT_MAPPING.items():
        if measurement == endpoint_or_measurement_name:
            try:
                category = get_endpoint_category(endpoint)
                behavior = get_collection_behavior(category)
                return behavior.get('export_prometheus', False)
            except ValueError:
                continue

    # Final fallback for truly uncategorized items (should be rare with proper categorization)
    return False

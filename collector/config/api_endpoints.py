"""
Centralized API endpoint definitions for E-Series Performance Analyzer

This module contains the definitive API endpoint mappings used by both
the main collector and the raw API collector to ensure consistency.
"""

# Main API endpoint mappings
API_ENDPOINTS = {
    # System configuration
    'system_config': 'devmgr/v2/storage-systems/{system_id}',
    'controller_config': 'devmgr/v2/storage-systems/{system_id}/controllers',

    # Storage configuration
    'storage_pools': 'devmgr/v2/storage-systems/{system_id}/storage-pools',
    'volumes_config': 'devmgr/v2/storage-systems/{system_id}/volumes',
    'volume_mappings_config': 'devmgr/v2/storage-systems/{system_id}/volume-mappings',
    'drive_config': 'devmgr/v2/storage-systems/{system_id}/drives',
    'ethernet_interface_config': 'devmgr/v2/storage-systems/{system_id}/configuration/ethernet-interfaces',
    'interfaces_config': 'devmgr/v2/storage-systems/{system_id}/interfaces',

    # Host connectivity
    'hosts': 'devmgr/v2/storage-systems/{system_id}/hosts',
    'host_groups': 'devmgr/v2/storage-systems/{system_id}/host-groups',

    # Performance endpoints
    'analyzed_volume_statistics': 'devmgr/v2/storage-systems/{system_id}/analysed-volume-statistics',
    'analyzed_drive_statistics': 'devmgr/v2/storage-systems/{system_id}/analysed-drive-statistics',
    'analyzed_system_statistics': 'devmgr/v2/storage-systems/{system_id}/analysed-system-statistics',
    'analyzed_interface_statistics': 'devmgr/v2/storage-systems/{system_id}/analysed-interface-statistics',
    'analyzed_controller_statistics': 'devmgr/v2/storage-systems/{system_id}/analyzed/controller-statistics?statisticsFetchTime=60',

    # Hardware inventory
    'hardware_inventory': 'devmgr/v2/storage-systems/{system_id}/hardware-inventory',
    'tray_config': '/devmgr/v2/hardware-inventory/trays',
    # 'ethernet_interface_config': '/devmgr/v2/networking/ethernet/interfaces',    # DUPLICATE: was overriding the config endpoint above - but unclear why never collected
    'env_power': 'devmgr/v2/storage-systems/{system_id}/symbol/getEnergyStarData',
    'env_temperature': 'devmgr/v2/storage-systems/{system_id}/symbol/getEnclosureTemperatures',

    # Events and status endpoints
    'system_failures': 'devmgr/v2/storage-systems/{system_id}/failures',
    'lockdown_status': 'devmgr/v2/storage-systems/{system_id}/lockdownstatus',
    'volume_parity_check_status': 'devmgr/v2/storage-systems/{system_id}/volumes/check-volume-parity/jobs',
    'volume_parity_job_check_errors': 'devmgr/v2/storage-systems/{system_id}/volumes/check-volume-parity/jobs/errors',
    'data_parity_scan_job_status': 'devmgr/v2/storage-systems/{system_id}/volumes/data-parity-repair-volume/jobs',
    'volume_copy_jobs': 'devmgr/v2/storage-systems/{system_id}/volume-copy-jobs',
    'volume_copy_job_progress': 'devmgr/v2/storage-systems/{system_id}/volume-copy-jobs-control',
    'drives_erase_progress': 'devmgr/v2/storage-systems/{system_id}/drives/erase/progress',
    'storage_pools_action_progress': 'devmgr/v2/storage-systems/{system_id}/storage-pools/{id}/action-progress',

    # Advanced features
    'ssd_cache': 'devmgr/v2/storage-systems/{system_id}/flash-cache',
    'snapshot_schedules': 'devmgr/v2/storage-systems/{system_id}/snapshot-schedules',
    'snapshot_groups': 'devmgr/v2/storage-systems/{system_id}/snapshot-groups',
    'snapshot_volumes': 'devmgr/v2/storage-systems/{system_id}/snapshot-volumes',
    'snapshot_images': 'devmgr/v2/storage-systems/{system_id}/snapshot-images',
    'mirrors': 'devmgr/v2/storage-systems/{system_id}/mirror-pairs',
    'async_mirrors': 'devmgr/v2/storage-systems/{system_id}/async-mirrors',

    # ID-dependent endpoints (require parent object IDs)
    'snapshot_groups_repository_utilization': 'devmgr/v2/storage-systems/{system_id}/snapshot-groups/{id}/repository-utilization',
    'volume_expansion_progress': 'devmgr/v2/storage-systems/{system_id}/volumes/{id}/expand',
}

# ID dependency mapping for endpoints that require parent object IDs
ID_DEPENDENCIES = {
    'snapshot_groups_repository_utilization': {
        'id_source': 'snapshot_groups',
        'id_field': 'pitGroupRef',
        'description': 'Repository utilization for each snapshot group'
    },
    'storage_pools_action_progress': {
        'id_source': 'storage_pools',
        'id_field': 'volumeGroupRef',
        'description': 'Action progress for each storage pool'
    },
    'volume_expansion_progress': {
        'id_source': 'volumes_config',
        'id_field': 'volumeRef',
        'description': 'Expansion progress for each volume'
    }
}
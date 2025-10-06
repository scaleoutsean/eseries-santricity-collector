# InfluxDB Schema for EPA 4

## Measurements

- [config_controller](#measurement-config_controller)
- [config_drives](#measurement-config_drives)
- [config_ethernet_interface](#measurement-config_ethernet_interface)
- [config_hosts](#measurement-config_hosts)
- [config_interfaces](#measurement-config_interfaces)
- [config_snapshot_groups](#measurement-config_snapshot_groups)
- [config_snapshot_schedules](#measurement-config_snapshot_schedules)
- [config_snapshots](#measurement-config_snapshots)
- [config_storage_pools](#measurement-config_storage_pools)
- [config_system](#measurement-config_system)
- [config_volume_mappings](#measurement-config_volume_mappings)
- [config_volumes](#measurement-config_volumes)
- [env_power](#measurement-env_power)
- [env_temperature](#measurement-env_temperature)
- [events_lockdown_status](#measurement-events_lockdown_status)
- [events_system_failures](#measurement-events_system_failures)
- [performance_controller_statistics](#measurement-performance_controller_statistics)
- [performance_drive_statistics](#measurement-performance_drive_statistics)
- [performance_interface_statistics](#measurement-performance_interface_statistics)
- [performance_system_statistics](#measurement-performance_system_statistics)
- [performance_volume_statistics](#measurement-performance_volume_statistics)

<a id="measurement-config_controller"></a>
## Measurement: config_controller

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_controller | controller_id |
| config_controller | controller_status |
| config_controller | controller_unit |
| config_controller | storage_system_name |
| config_controller | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_controller | active | boolean |
| config_controller | boot_time | integer |
| config_controller | cache_memory_size | integer |
| config_controller | controller_error_mode | string |
| config_controller | controller_ref | string |
| config_controller | flash_cache_memory_size | integer |
| config_controller | has_tray_identity_indicator | boolean |
| config_controller | id | string |
| config_controller | locate_in_progress | boolean |
| config_controller | manufacturer | string |
| config_controller | model_name | string |
| config_controller | part_number | string |
| config_controller | physical_cache_memory_size | integer |
| config_controller | processor_memory_size | integer |
| config_controller | serial_number | string |
| config_controller | status | string |

<a id="measurement-config_drives"></a>
## Measurement: config_drives

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_drives | drive_type |
| config_drives | pool_name |
| config_drives | slot |
| config_drives | storage_system_name |
| config_drives | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_drives | available | boolean |
| config_drives | blk_size | integer |
| config_drives | blk_size_physical | integer |
| config_drives | cause | string |
| config_drives | current_speed | string |
| config_drives | current_volume_group_ref | string |
| config_drives | drive_media_type | string |
| config_drives | drive_ref | string |
| config_drives | drive_security_type | string |
| config_drives | dulbe_capable | boolean |
| config_drives | fde_capable | boolean |
| config_drives | fde_enabled | boolean |
| config_drives | fde_locked | boolean |
| config_drives | fips_capable | boolean |
| config_drives | firmware_version | string |
| config_drives | has_degraded_channel | boolean |
| config_drives | hot_spare | boolean |
| config_drives | id | string |
| config_drives | invalid_drive_data | boolean |
| config_drives | lowest_aligned_lba | string |
| config_drives | manufacturer | string |
| config_drives | manufacturer_date | string |
| config_drives | max_speed | string |
| config_drives | mirror_drive | string |
| config_drives | non_redundant_access | boolean |
| config_drives | offline | boolean |
| config_drives | phy_drive_type | string |
| config_drives | product_id | string |
| config_drives | raw_capacity | integer |
| config_drives | sanitize_capable | boolean |
| config_drives | serial_number | string |
| config_drives | software_version | string |
| config_drives | spared_for_drive_ref | string |
| config_drives | spindle_speed | integer |
| config_drives | status | string |
| config_drives | uncertified | boolean |
| config_drives | usable_capacity | string |
| config_drives | volume_group_index | integer |
| config_drives | working_channel | integer |
| config_drives | world_wide_name | string |

<a id="measurement-config_ethernet_interface"></a>
## Measurement: config_ethernet_interface

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_ethernet_interface | controller_ref |
| config_ethernet_interface | controller_unit |
| config_ethernet_interface | interface_id |
| config_ethernet_interface | interface_type |
| config_ethernet_interface | storage_system_name |
| config_ethernet_interface | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_ethernet_interface | alias | string |
| config_ethernet_interface | bootp_used | boolean |
| config_ethernet_interface | channel | integer |
| config_ethernet_interface | configured_speed_setting | string |
| config_ethernet_interface | controller_slot | integer |
| config_ethernet_interface | current_speed | string |
| config_ethernet_interface | full_duplex | boolean |
| config_ethernet_interface | gateway_ip | integer |
| config_ethernet_interface | id | string |
| config_ethernet_interface | interface_name | string |
| config_ethernet_interface | interface_ref | string |
| config_ethernet_interface | ip | integer |
| config_ethernet_interface | ipv4_address | string |
| config_ethernet_interface | ipv4_address_config_method | string |
| config_ethernet_interface | ipv4_enabled | boolean |
| config_ethernet_interface | ipv4_gateway_address | string |
| config_ethernet_interface | ipv4_subnet_mask | string |
| config_ethernet_interface | ipv6_address_config_method | string |
| config_ethernet_interface | ipv6_enabled | boolean |
| config_ethernet_interface | is_network_trace_capable | boolean |
| config_ethernet_interface | link_status | string |
| config_ethernet_interface | mac_addr | string |
| config_ethernet_interface | reserved1 | string |
| config_ethernet_interface | rlogin_enabled | boolean |
| config_ethernet_interface | setup_error | string |
| config_ethernet_interface | speed | integer |
| config_ethernet_interface | subnet_mask | integer |

<a id="measurement-config_hosts"></a>
## Measurement: config_hosts

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_hosts | host_id |
| config_hosts | host_name |
| config_hosts | hostgroup_id |
| config_hosts | hostgroup_name |
| config_hosts | storage_system_name |
| config_hosts | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_hosts | cluster_ref | string |
| config_hosts | confirm_lunmapping_creation | boolean |
| config_hosts | host_ref | string |
| config_hosts | host_type_index | integer |
| config_hosts | id | string |
| config_hosts | is_large_block_format_host | boolean |
| config_hosts | is_lun0_restricted | boolean |
| config_hosts | is_sacontrolled | boolean |
| config_hosts | label | string |
| config_hosts | name | string |
| config_hosts | protection_information_capable_access_method | boolean |

<a id="measurement-config_interfaces"></a>
## Measurement: config_interfaces

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_interfaces | controller_ref |
| config_interfaces | controller_unit |
| config_interfaces | interface_id |
| config_interfaces | interface_type |
| config_interfaces | storage_system_name |
| config_interfaces | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_interfaces | channel | integer |
| config_interfaces | channel_type | string |
| config_interfaces | id | string |
| config_interfaces | interface_ref | string |
| config_interfaces | is_degraded | integer |
| config_interfaces | revision | integer |

<a id="measurement-config_snapshot_groups"></a>
## Measurement: config_snapshot_groups

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_snapshot_groups | config_id |
| config_snapshot_groups | storage_system_name |
| config_snapshot_groups | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_snapshot_groups | action | string |
| config_snapshot_groups | auto_delete_limit | integer |
| config_snapshot_groups | base_volume | string |
| config_snapshot_groups | cluster_size | integer |
| config_snapshot_groups | consistency_group | boolean |
| config_snapshot_groups | consistency_group_ref | string |
| config_snapshot_groups | creation_pending_status | string |
| config_snapshot_groups | full_warn_threshold | integer |
| config_snapshot_groups | id | string |
| config_snapshot_groups | label | string |
| config_snapshot_groups | max_base_capacity | integer |
| config_snapshot_groups | max_repository_capacity | integer |
| config_snapshot_groups | name | string |
| config_snapshot_groups | pit_group_ref | string |
| config_snapshot_groups | rep_full_policy | string |
| config_snapshot_groups | repository_capacity | integer |
| config_snapshot_groups | repository_volume | string |
| config_snapshot_groups | rollback_priority | string |
| config_snapshot_groups | rollback_status | string |
| config_snapshot_groups | snapshot_count | integer |
| config_snapshot_groups | status | string |
| config_snapshot_groups | unusable_repository_capacity | integer |
| config_snapshot_groups | volume_handle | integer |

<a id="measurement-config_snapshot_schedules"></a>
## Measurement: config_snapshot_schedules

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_snapshot_schedules | config_id |
| config_snapshot_schedules | storage_system_name |
| config_snapshot_schedules | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_snapshot_schedules | action | string |
| config_snapshot_schedules | creation_time | string |
| config_snapshot_schedules | id | string |
| config_snapshot_schedules | last_run_time | string |
| config_snapshot_schedules | next_run_time | string |
| config_snapshot_schedules | sched_ref | string |
| config_snapshot_schedules | schedule_status | string |
| config_snapshot_schedules | stop_time | string |
| config_snapshot_schedules | target_object | string |

<a id="measurement-config_snapshots"></a>
## Measurement: config_snapshots

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_snapshots | config_id |
| config_snapshots | storage_system_name |
| config_snapshots | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_snapshots | active_cow | boolean |
| config_snapshots | base_vol | string |
| config_snapshots | consistency_group_id | string |
| config_snapshots | creation_method | string |
| config_snapshots | id | string |
| config_snapshots | is_rollback_source | boolean |
| config_snapshots | pit_capacity | integer |
| config_snapshots | pit_group_ref | string |
| config_snapshots | pit_ref | string |
| config_snapshots | pit_sequence_number | integer |
| config_snapshots | pit_timestamp | integer |
| config_snapshots | repository_capacity_utilization | integer |
| config_snapshots | status | string |

<a id="measurement-config_storage_pools"></a>
## Measurement: config_storage_pools

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_storage_pools | pool_id |
| config_storage_pools | pool_name |
| config_storage_pools | raid_level |
| config_storage_pools | storage_system_name |
| config_storage_pools | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_storage_pools | blk_size_recommended | integer |
| config_storage_pools | blk_size_supported | string |
| config_storage_pools | disk_pool | boolean |
| config_storage_pools | drawer_loss_protection | boolean |
| config_storage_pools | drive_block_format | string |
| config_storage_pools | drive_media_type | string |
| config_storage_pools | drive_physical_type | string |
| config_storage_pools | dulbe_enabled | boolean |
| config_storage_pools | free_space | integer |
| config_storage_pools | id | string |
| config_storage_pools | is_inaccessible | boolean |
| config_storage_pools | label | string |
| config_storage_pools | name | string |
| config_storage_pools | normalized_spindle_speed | string |
| config_storage_pools | offline | boolean |
| config_storage_pools | raid_status | string |
| config_storage_pools | reserved_space_allocated | boolean |
| config_storage_pools | security_level | string |
| config_storage_pools | security_type | string |
| config_storage_pools | sequence_num | integer |
| config_storage_pools | spindle_speed | integer |
| config_storage_pools | spindle_speed_match | boolean |
| config_storage_pools | state | string |
| config_storage_pools | total_raided_space | integer |
| config_storage_pools | tray_loss_protection | boolean |
| config_storage_pools | usage | string |
| config_storage_pools | used_space | integer |
| config_storage_pools | volume_group_ref | string |
| config_storage_pools | world_wide_name | string |

<a id="measurement-config_system"></a>
## Measurement: config_system

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_system | config_id |
| config_system | storage_system_name |
| config_system | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_system | asup_enabled | boolean |
| config_system | auto_load_balancing_enabled | boolean |
| config_system | certificate_status | string |
| config_system | chassis_serial_number | string |
| config_system | drive_count | integer |
| config_system | external_key_enabled | boolean |
| config_system | free_pool_space | integer |
| config_system | host_connectivity_reporting_enabled | boolean |
| config_system | host_spare_count_in_standby | integer |
| config_system | host_spares_used | integer |
| config_system | hot_spare_count | integer |
| config_system | hot_spare_size | integer |
| config_system | invalid_system_config | boolean |
| config_system | media_scan_period | integer |
| config_system | model | string |
| config_system | name | string |
| config_system | password_status | string |
| config_system | security_key_enabled | boolean |
| config_system | status | string |
| config_system | system_model | string |
| config_system | tray_count | integer |
| config_system | unconfigured_space | integer |
| config_system | used_pool_space | integer |
| config_system | wwn | string |

<a id="measurement-config_volume_mappings"></a>
## Measurement: config_volume_mappings

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_volume_mappings | pool_id |
| config_volume_mappings | pool_name |
| config_volume_mappings | storage_system_name |
| config_volume_mappings | storage_system_wwn |
| config_volume_mappings | volume_id |
| config_volume_mappings | volume_name |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_volume_mappings | id | string |
| config_volume_mappings | lun | integer |
| config_volume_mappings | lun_mapping_ref | string |
| config_volume_mappings | map_ref | string |
| config_volume_mappings | ssid | integer |
| config_volume_mappings | type | string |
| config_volume_mappings | volume_ref | string |

<a id="measurement-config_volumes"></a>
## Measurement: config_volumes

### Tags

| iox::measurement | tagKey |
| --- | --- |
| config_volumes | pool_id |
| config_volumes | pool_name |
| config_volumes | storage_system_name |
| config_volumes | storage_system_wwn |
| config_volumes | volume_id |
| config_volumes | volume_name |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| config_volumes | action | string |
| config_volumes | alloc_granularity | integer |
| config_volumes | application_tag_owned | boolean |
| config_volumes | async_mirror_source | boolean |
| config_volumes | async_mirror_target | boolean |
| config_volumes | blk_size | integer |
| config_volumes | blk_size_physical | integer |
| config_volumes | cache_mirroring_validate_protection_information | boolean |
| config_volumes | cache_pool_id | integer |
| config_volumes | capacity | integer |
| config_volumes | current_controller_id | string |
| config_volumes | current_manager | string |
| config_volumes | data_assurance | boolean |
| config_volumes | data_drive_count | integer |
| config_volumes | disk_pool | boolean |
| config_volumes | dss_max_segment_size | integer |
| config_volumes | dss_prealloc_enabled | boolean |
| config_volumes | expected_protection_information_app_tag | integer |
| config_volumes | extended_unique_identifier | string |
| config_volumes | extreme_protection | boolean |
| config_volumes | flash_cached | boolean |
| config_volumes | host | string |
| config_volumes | host_group | string |
| config_volumes | host_unmap_enabled | boolean |
| config_volumes | id | string |
| config_volumes | increasing_by | integer |
| config_volumes | label | string |
| config_volumes | mapped | boolean |
| config_volumes | mgmt_client_attribute | integer |
| config_volumes | name | string |
| config_volumes | object_type | string |
| config_volumes | offline | boolean |
| config_volumes | online_volume_copy | boolean |
| config_volumes | parity_drive_count | integer |
| config_volumes | pit_base_volume | boolean |
| config_volumes | pre_read_redundancy_check_enabled | boolean |
| config_volumes | preferred_controller_id | string |
| config_volumes | preferred_manager | string |
| config_volumes | protection_information_capable | boolean |
| config_volumes | protection_type | string |
| config_volumes | raid_level | string |
| config_volumes | recon_priority | integer |
| config_volumes | remote_mirror_source | boolean |
| config_volumes | remote_mirror_target | boolean |
| config_volumes | repaired_block_count | integer |
| config_volumes | sector_offset | integer |
| config_volumes | segment_size | integer |
| config_volumes | status | string |
| config_volumes | thin_provisioned | boolean |
| config_volumes | total_size_in_bytes | integer |
| config_volumes | volume_copy_source | boolean |
| config_volumes | volume_copy_target | boolean |
| config_volumes | volume_full | boolean |
| config_volumes | volume_group_ref | string |
| config_volumes | volume_handle | integer |
| config_volumes | volume_ref | string |
| config_volumes | volume_use | string |
| config_volumes | world_wide_name | string |
| config_volumes | wwn | string |

<a id="measurement-env_power"></a>
## Measurement: env_power

### Tags

| iox::measurement | tagKey |
| --- | --- |
| env_power | return_code |
| env_power | storage_system_name |
| env_power | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| env_power | number_of_trays | integer |
| env_power | total_power | integer |
| env_power | tray_0_number_of_power_supplies | integer |
| env_power | tray_0_psu_0_power | float |

<a id="measurement-env_temperature"></a>
## Measurement: env_temperature

### Tags

| iox::measurement | tagKey |
| --- | --- |
| env_temperature | sensor_ref |
| env_temperature | storage_system_name |
| env_temperature | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| env_temperature | temp | float |

<a id="measurement-events_lockdown_status"></a>
## Measurement: events_lockdown_status

### Tags

| iox::measurement | tagKey |
| --- | --- |
| events_lockdown_status | lockdown_state |
| events_lockdown_status | storage_system_name |
| events_lockdown_status | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| events_lockdown_status | is_lockdown | integer |
| events_lockdown_status | lockdown_type | string |

<a id="measurement-events_system_failures"></a>
## Measurement: events_system_failures

### Tags

| iox::measurement | tagKey |
| --- | --- |
| events_system_failures | failure_type |
| events_system_failures | object_ref |
| events_system_failures | object_type |
| events_system_failures | storage_system_name |
| events_system_failures | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| events_system_failures | failure_occurred | integer |

<a id="measurement-performance_controller_statistics"></a>
## Measurement: performance_controller_statistics

### Tags

| iox::measurement | tagKey |
| --- | --- |
| performance_controller_statistics | controller_id |
| performance_controller_statistics | controller_unit |
| performance_controller_statistics | source_controller |
| performance_controller_statistics | storage_system_name |
| performance_controller_statistics | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| performance_controller_statistics | average_read_op_size | float |
| performance_controller_statistics | average_write_op_size | float |
| performance_controller_statistics | cache_hit_bytes_percent | float |
| performance_controller_statistics | combined_response_time | float |
| performance_controller_statistics | combined_throughput | float |
| performance_controller_statistics | cpu_avg_utilization | float |
| performance_controller_statistics | full_stripe_writes_bytes_percent | float |
| performance_controller_statistics | max_cpu_utilization | float |
| performance_controller_statistics | mirror_bytes_percent | float |
| performance_controller_statistics | random_ios_percent | float |
| performance_controller_statistics | read_response_time | float |
| performance_controller_statistics | read_throughput | float |
| performance_controller_statistics | write_response_time | float |
| performance_controller_statistics | write_throughput | float |

<a id="measurement-performance_drive_statistics"></a>
## Measurement: performance_drive_statistics

### Tags

| iox::measurement | tagKey |
| --- | --- |
| performance_drive_statistics | controller_id |
| performance_drive_statistics | drive_id |
| performance_drive_statistics | drive_slot |
| performance_drive_statistics | storage_system_name |
| performance_drive_statistics | storage_system_wwn |
| performance_drive_statistics | tray_id |
| performance_drive_statistics | volume_group_id |
| performance_drive_statistics | volume_group_name |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| performance_drive_statistics | average_queue_depth | float |
| performance_drive_statistics | average_read_op_size | float |
| performance_drive_statistics | average_write_op_size | float |
| performance_drive_statistics | combined_response_time | float |
| performance_drive_statistics | combined_throughput | float |
| performance_drive_statistics | queue_depth_max | float |
| performance_drive_statistics | random_bytes_percent | float |
| performance_drive_statistics | random_ios_percent | float |
| performance_drive_statistics | read_response_time | float |
| performance_drive_statistics | read_throughput | float |
| performance_drive_statistics | read_time_max | float |
| performance_drive_statistics | write_response_time | float |
| performance_drive_statistics | write_throughput | float |
| performance_drive_statistics | write_time_max | float |

<a id="measurement-performance_interface_statistics"></a>
## Measurement: performance_interface_statistics

### Tags

| iox::measurement | tagKey |
| --- | --- |
| performance_interface_statistics | channel_number |
| performance_interface_statistics | channel_type |
| performance_interface_statistics | controller_id |
| performance_interface_statistics | controller_unit |
| performance_interface_statistics | interface_id |
| performance_interface_statistics | storage_system_name |
| performance_interface_statistics | storage_system_wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| performance_interface_statistics | average_read_op_size | float |
| performance_interface_statistics | average_write_op_size | float |
| performance_interface_statistics | channel_error_counts | float |
| performance_interface_statistics | combined_response_time | float |
| performance_interface_statistics | combined_throughput | float |
| performance_interface_statistics | queue_depth_max | float |
| performance_interface_statistics | queue_depth_total | float |
| performance_interface_statistics | read_response_time | float |
| performance_interface_statistics | read_throughput | float |
| performance_interface_statistics | write_response_time | float |
| performance_interface_statistics | write_throughput | float |

<a id="measurement-performance_system_statistics"></a>
## Measurement: performance_system_statistics

### Tags

| iox::measurement | tagKey |
| --- | --- |
| performance_system_statistics | name |
| performance_system_statistics | source_controller |
| performance_system_statistics | storage_system_name |
| performance_system_statistics | storage_system_wwn |
| performance_system_statistics | wwn |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| performance_system_statistics | average_read_op_size | float |
| performance_system_statistics | average_write_op_size | float |
| performance_system_statistics | cache_hit_bytes_percent | float |
| performance_system_statistics | combined_hit_response_time | float |
| performance_system_statistics | combined_response_time | float |
| performance_system_statistics | combined_throughput | float |
| performance_system_statistics | cpu_avg_utilization | float |
| performance_system_statistics | ddp_bytes_percent | float |
| performance_system_statistics | full_stripe_writes_bytes_percent | float |
| performance_system_statistics | max_cpu_utilization | float |
| performance_system_statistics | max_possible_bps_under_current_load | float |
| performance_system_statistics | max_possible_iops_under_current_load | float |
| performance_system_statistics | mirror_bytes_percent | float |
| performance_system_statistics | raid0_bytes_percent | float |
| performance_system_statistics | raid1_bytes_percent | float |
| performance_system_statistics | raid5_bytes_percent | float |
| performance_system_statistics | raid6_bytes_percent | float |
| performance_system_statistics | random_ios_percent | float |
| performance_system_statistics | read_hit_response_time | float |
| performance_system_statistics | read_response_time | float |
| performance_system_statistics | read_throughput | float |
| performance_system_statistics | write_hit_response_time | float |
| performance_system_statistics | write_response_time | float |
| performance_system_statistics | write_throughput | float |

<a id="measurement-performance_volume_statistics"></a>
## Measurement: performance_volume_statistics

### Tags

| iox::measurement | tagKey |
| --- | --- |
| performance_volume_statistics | controller_id |
| performance_volume_statistics | controller_unit |
| performance_volume_statistics | host |
| performance_volume_statistics | host_group |
| performance_volume_statistics | storage_pool |
| performance_volume_statistics | storage_system_name |
| performance_volume_statistics | storage_system_wwn |
| performance_volume_statistics | volume_id |
| performance_volume_statistics | volume_name |

### Fields

| iox::measurement | fieldKey | fieldType |
| --- | --- | --- |
| performance_volume_statistics | average_queue_depth | float |
| performance_volume_statistics | average_read_op_size | float |
| performance_volume_statistics | average_write_op_size | float |
| performance_volume_statistics | combined_response_time | float |
| performance_volume_statistics | combined_throughput | float |
| performance_volume_statistics | queue_depth_max | float |
| performance_volume_statistics | queue_depth_total | float |
| performance_volume_statistics | random_bytes_percent | float |
| performance_volume_statistics | random_ios_percent | float |
| performance_volume_statistics | read_cache_utilization | float |
| performance_volume_statistics | read_response_time | float |
| performance_volume_statistics | read_throughput | float |
| performance_volume_statistics | write_cache_utilization | float |
| performance_volume_statistics | write_response_time | float |
| performance_volume_statistics | write_throughput | float |


"""
Shared Configuration Enrichment for E-Series Performance Analyzer

This module provides enrichment for simpler configuration types that don't
warrant dedicated enrichers due to lower complexity or field counts.

Handles config types with < 30 keys or simple structure:
- Volume configs (8 keys) - Volume mappings and basic volume info
- Host configs - Host group and individual host configurations
- Ethernet configs - Network interface configurations
- Hardware configs - Basic hardware component info
- System configs - High-level system settings
- Snapshot configs - Point-in-time snapshot configurations

Uses shared enrichment patterns while maintaining type-specific logic.
"""

import logging
from typing import Dict, Any, Optional
from .config_enrichment import BaseConfigEnricher

LOG = logging.getLogger(__name__)

class SharedConfigEnricher(BaseConfigEnricher):
    """
    Shared enricher for simpler configuration types.

    Provides type-appropriate enrichment without the complexity
    needed for drive/controller/storage configs.
    """

    def __init__(self, system_enricher=None, volume_enricher=None):
        """Initialize shared config enricher."""
        super().__init__(system_enricher)
        self.volume_enricher = volume_enricher

        # E-Series host type index to human-readable mapping
        # Based on complete E-Series host type definitions from API
        #
        # Without this mapping, Grafana users would need to manually
        # discover what each hostTypeIndex (0-29) means by either:
        # - Using Swagger API docs (if accessible)
        # - Trial-and-error in lab environments
        # - Creating Grafana aliases based on E-Series/SANtricity documentation or KBs
        self.host_type_map = {
            # Factory Default
            0: {'name': 'Factory Default', 'os': 'unknown', 'category': 'other'},

            # Windows variants
            1: {'name': 'Windows (clustered or non-clustered)', 'os': 'windows', 'category': 'windows'},
            8: {'name': 'Windows Clustered (deprecated)', 'os': 'windows', 'category': 'windows'},
            23: {'name': 'Windows (ATTO)', 'os': 'windows', 'category': 'windows'},

            # Linux variants
            6: {'name': 'Linux (MPP/RDAC)', 'os': 'linux', 'category': 'unix'},
            7: {'name': 'Linux DM-MP (Kernel 3.9 or earlier)', 'os': 'linux', 'category': 'unix'},
            24: {'name': 'Linux (ATTO)', 'os': 'linux', 'category': 'unix'},
            27: {'name': 'Linux (Veritas DMP)', 'os': 'linux', 'category': 'unix'},
            28: {'name': 'Linux DM-MP (Kernel 3.10 or later)', 'os': 'linux', 'category': 'unix'},

            # VMware variants
            10: {'name': 'VMware ESXi', 'os': 'vmware', 'category': 'virtualization'},

            # Solaris variants
            2: {'name': 'Solaris (version 10 or earlier)', 'os': 'solaris', 'category': 'unix'},
            17: {'name': 'Solaris (v11 or later)', 'os': 'solaris', 'category': 'unix'},

            # AIX variants
            9: {'name': 'AIX MPIO', 'os': 'aix', 'category': 'unix'},

            # HP-UX
            15: {'name': 'HP-UX', 'os': 'hpux', 'category': 'unix'},

            # Other Unix/Linux systems
            18: {'name': 'IBM SVC', 'os': 'other', 'category': 'storage'},
            22: {'name': 'Mac OS (ATTO)', 'os': 'macos', 'category': 'unix'},
            26: {'name': 'FlexArray (ALUA)', 'os': 'other', 'category': 'storage'},
            29: {'name': 'ATTO Cluster (all operating systems)', 'os': 'other', 'category': 'clustering'},
        }

        # Common status mappings across config types
        self.status_map = {
            'optimal': 'healthy',
            'ok': 'healthy',
            'good': 'healthy',
            'online': 'healthy',
            'active': 'healthy',
            'degraded': 'warning',
            'warning': 'warning',
            'inactive': 'warning',
            'failed': 'critical',
            'offline': 'critical',
            'error': 'critical',
            'unknown': 'unknown'
        }

        # Volume types for classification
        self.volume_types = {
            'thick': 'thick_provisioned',
            'thin': 'thin_provisioned',
            'repository': 'repository',
            'snapshot': 'snapshot'
        }

    def enrich_item(self, raw_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Apply type-appropriate enrichment based on config type.

        Dispatches to specific enrichment methods based on config type
        while maintaining shared patterns and standardization.
        """
        enriched_item = raw_item.copy()

        # Dispatch to type-specific enrichment
        config_type_lower = config_type.lower()

        LOG.debug(f"SharedConfigEnricher.enrich: config_type='{config_type}', config_type_lower='{config_type_lower}'")

        # Check for volume mappings first (before generic volume)
        if 'volume_mappings' in config_type_lower or 'volumemappings' in config_type_lower:
            LOG.debug(f"SharedConfigEnricher: Dispatching to volume mappings enrichment for {config_type}")
            return self._enrich_volume_mappings_config(enriched_item, config_type)
        elif 'volume_mapping' in config_type_lower or 'volumemapping' in config_type_lower:  # Also check singular form
            LOG.debug(f"SharedConfigEnricher: Dispatching to volume mappings enrichment (singular) for {config_type}")
            return self._enrich_volume_mappings_config(enriched_item, config_type)
        elif 'volume' in config_type_lower:
            return self._enrich_volume_config(enriched_item, config_type)
        elif 'drive' in config_type_lower:
            return self._enrich_drive_config(enriched_item, config_type)
        elif 'host' in config_type_lower and 'groups' not in config_type_lower:
            return self._enrich_host_config(enriched_item, config_type)
        elif 'hostgroups' in config_type_lower or 'cluster' in config_type_lower:
            return self._enrich_hostgroup_config(enriched_item, config_type)
        elif 'controller' in config_type_lower:
            return self._enrich_controller_config(enriched_item, config_type)
        elif 'ethernet' in config_type_lower:
            return self._enrich_ethernet_config(enriched_item, config_type)
        elif 'interface' in config_type_lower:
            return self._enrich_interface_config(enriched_item, config_type)
        elif 'snapshot' in config_type_lower:
            return self._enrich_snapshot_config(enriched_item, config_type)
        elif 'hardware' in config_type_lower:
            return self._enrich_hardware_config(enriched_item, config_type)
        elif 'system' in config_type_lower:
            return self._enrich_system_config(enriched_item, config_type)
        else:
            # Generic enrichment for unknown types
            return self._enrich_generic_config(enriched_item, config_type)

    def _enrich_volume_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich volume configuration data.

        Focus on volume identity, capacity, and pool assignment.
        """
        # === VOLUME IDENTITY ===
        volume_ref = (enriched_item.get('volumeRef') or
                     enriched_item.get('id') or
                     enriched_item.get('ref'))
        if volume_ref:
            enriched_item['volume_id'] = volume_ref
            enriched_item['volume_ref'] = volume_ref

        # Volume name/label
        volume_name = enriched_item.get('label') or enriched_item.get('name')
        if volume_name:
            enriched_item['volume_name'] = volume_name

        # === CAPACITY INFORMATION ===
        # Volume capacity
        capacity = enriched_item.get('capacity')
        if capacity:
            try:
                capacity_gb = int(capacity) // (1024**3)
                enriched_item['volume_capacity_gb'] = capacity_gb

                # Size tier
                if capacity_gb >= 160000:  # 16TB+
                    enriched_item['volume_size_tier'] = 'very_large'
                elif capacity_gb >= 4000:  # 4TB+
                    enriched_item['volume_size_tier'] = 'large'
                elif capacity_gb >= 1000:   # 1TB+
                    enriched_item['volume_size_tier'] = 'medium'
                else:
                    enriched_item['volume_size_tier'] = 'small'
            except (ValueError, TypeError):
                pass

        # === POOL ASSIGNMENT ===
        # Volume group (storage pool) reference
        volume_group_ref = enriched_item.get('volumeGroupRef')
        if volume_group_ref:
            enriched_item['volume_pool_ref'] = volume_group_ref

            # Add pool name if volume_enricher is available
            if self.volume_enricher and hasattr(self.volume_enricher, 'pool_lookup'):
                pool = self.volume_enricher.pool_lookup.get(volume_group_ref)
                if pool:
                    pool_name = pool.get('name') or pool.get('label')
                    if pool_name:
                        enriched_item['pool_name'] = pool_name

        # === VOLUME CHARACTERISTICS ===
        # Provisioning type
        thin_provisioned = enriched_item.get('thinProvisioned')
        if thin_provisioned is not None:
            if str(thin_provisioned).lower() == 'true':
                enriched_item['volume_provisioning'] = 'thin'
            else:
                enriched_item['volume_provisioning'] = 'thick'

        # Volume status
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item['volume_status'] = status
            enriched_item['volume_health'] = self.status_map.get(status, 'unknown')

        # === MAPPING INFORMATION ===
        # LUN mapping (for host connectivity)
        lun = enriched_item.get('lun')
        if lun is not None:
            enriched_item['volume_lun'] = lun

        # Mapped host reference
        mapped_to_ref = enriched_item.get('mapRef')
        if mapped_to_ref:
            enriched_item['volume_mapped_to'] = mapped_to_ref
            enriched_item['volume_mapped'] = 'true'
        else:
            enriched_item['volume_mapped'] = 'false'

        # === HOST AND HOST GROUP ENRICHMENT ===
        # Add host and host_group tags using volume_enricher mapping data
        if self.volume_enricher and volume_ref:
            LOG.debug(f"SharedConfigEnricher: Looking up volume_ref={volume_ref}")
            LOG.debug(f"SharedConfigEnricher: volume_enricher has {len(self.volume_enricher.volume_mappings)} volume mappings")
            LOG.debug(f"SharedConfigEnricher: volume_enricher has {len(self.volume_enricher.host_lookup)} host lookups")
            LOG.debug(f"SharedConfigEnricher: volume_enricher has {len(self.volume_enricher.hostgroup_lookup)} hostgroup lookups")

            # Get mappings for this volume from volume_enricher
            vol_mappings = self.volume_enricher.volume_mappings.get(volume_ref, [])
            LOG.debug(f"SharedConfigEnricher: Found {len(vol_mappings)} mappings for volume {volume_ref}")

            host_names = []
            host_group_names = set()

            for mapping in vol_mappings:
                map_ref = mapping.get('mapRef')
                mapping_type = mapping.get('type')
                LOG.debug(f"SharedConfigEnricher: Processing mapping type={mapping_type}, map_ref={map_ref}")

                if mapping_type == 'host':
                    # Direct host mapping
                    host = self.volume_enricher.host_lookup.get(map_ref)
                    if host:
                        host_name = host.get('label', host.get('name', 'unknown'))
                        host_names.append(host_name)
                        LOG.debug(f"SharedConfigEnricher: Found host {host_name} for volume {volume_ref}")
                        # Check if host is in a group
                        cluster_ref = host.get('clusterRef')
                        if cluster_ref:
                            hostgroup = self.volume_enricher.hostgroup_lookup.get(cluster_ref)
                            if hostgroup:
                                host_group_names.add(hostgroup.get('name', 'unknown'))
                                LOG.debug(f"SharedConfigEnricher: Found hostgroup {hostgroup.get('name')} for host {host_name}")

                elif mapping_type == 'cluster':
                    # Host group mapping - get all hosts in the group
                    hostgroup = self.volume_enricher.hostgroup_lookup.get(map_ref)
                    if hostgroup:
                        host_group_names.add(hostgroup.get('name', 'unknown'))
                        LOG.debug(f"SharedConfigEnricher: Found hostgroup {hostgroup.get('name')} for volume {volume_ref}")
                        # Find all hosts that are members of this group
                        for host_id, host in self.volume_enricher.host_lookup.items():
                            if host.get('clusterRef') == map_ref:
                                host_name = host.get('label', host.get('name', 'unknown'))
                                host_names.append(host_name)
                                LOG.debug(f"SharedConfigEnricher: Found host {host_name} in hostgroup for volume {volume_ref}")

            # Add host and host_group tags
            enriched_item['host'] = ','.join(sorted(set(host_names))) if host_names else ''
            enriched_item['host_group'] = ','.join(sorted(host_group_names)) if host_group_names else ''
            LOG.debug(f"SharedConfigEnricher: Final enrichment for volume {volume_ref}: host='{enriched_item['host']}', host_group='{enriched_item['host_group']}'")
        else:
            LOG.debug(f"SharedConfigEnricher: No volume_enricher or volume_ref for config item")
            enriched_item['host'] = ''
            enriched_item['host_group'] = ''

        return enriched_item

    def _enrich_volume_mappings_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich volume mappings configuration data.

        Volume mappings contain volumeRef that needs to be cross-referenced
        with volume configs to get pool information (volumeGroupRef, pool_name).
        """
        LOG.debug(f"Volume mapping enrichment starting for config_type: {config_type}")

        # === VOLUME CROSS-REFERENCE ===
        volume_ref = enriched_item.get('volumeRef')
        LOG.debug(f"Volume mapping - volumeRef: {volume_ref}")

        if volume_ref and self.volume_enricher and hasattr(self.volume_enricher, 'volume_lookup'):
            LOG.debug(f"Volume mapping - volume_enricher available, volume_lookup has {len(self.volume_enricher.volume_lookup)} volumes")
            # Look up the referenced volume config to get pool information
            referenced_volume = self.volume_enricher.volume_lookup.get(volume_ref)
            if referenced_volume:
                LOG.debug(f"Volume mapping cross-reference: found volume {volume_ref}")

                # Extract pool information from referenced volume
                volume_group_ref = referenced_volume.get('volumeGroupRef')
                if volume_group_ref:
                    enriched_item['pool_id'] = volume_group_ref
                    enriched_item['volume_pool_ref'] = volume_group_ref

                    # Get pool name from volume enricher
                    if hasattr(self.volume_enricher, 'pool_lookup'):
                        pool = self.volume_enricher.pool_lookup.get(volume_group_ref)
                        if pool:
                            pool_name = pool.get('name') or pool.get('label')
                            if pool_name:
                                enriched_item['pool_name'] = pool_name
                                LOG.debug(f"Volume mapping enriched with pool_name: {pool_name}")

                # Extract volume name from referenced volume
                volume_name = referenced_volume.get('label') or referenced_volume.get('name')
                if volume_name:
                    enriched_item['volume_name'] = volume_name
                    LOG.debug(f"Volume mapping enriched with volume_name: {volume_name}")
            else:
                LOG.debug(f"Volume mapping volumeRef {volume_ref} not found in volume_lookup")
                LOG.debug(f"Volume mapping - available volume IDs: {list(self.volume_enricher.volume_lookup.keys()) if self.volume_enricher and hasattr(self.volume_enricher, 'volume_lookup') else 'N/A'}")
        else:
            if not volume_ref:
                LOG.debug(f"Volume mapping - no volumeRef found in mapping data")
            elif not self.volume_enricher:
                LOG.debug(f"Volume mapping - volume_enricher not available")
            elif not hasattr(self.volume_enricher, 'volume_lookup'):
                LOG.debug(f"Volume mapping - volume_enricher has no volume_lookup attribute")

        # === MAPPING-SPECIFIC ENRICHMENT ===
        # LUN mapping information
        lun = enriched_item.get('lun')
        if lun is not None:
            enriched_item['volume_lun'] = lun

        # Map reference (host or host group being mapped to)
        map_ref = enriched_item.get('mapRef')
        if map_ref:
            enriched_item['volume_mapped_to'] = map_ref
            enriched_item['volume_mapped'] = 'true'
        else:
            enriched_item['volume_mapped'] = 'false'

        # Mapping type (host or cluster/hostgroup)
        mapping_type = enriched_item.get('type')
        if mapping_type:
            enriched_item['volume_mapping_type'] = mapping_type

        return enriched_item

    def _enrich_drive_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich drive configuration data.

        Focus on drive identity, physical location, and pool assignment.
        """
        # === DRIVE IDENTITY ===
        drive_ref = (enriched_item.get('driveRef') or
                    enriched_item.get('id') or
                    enriched_item.get('ref'))
        if drive_ref:
            enriched_item['drive_id'] = drive_ref
            enriched_item['drive_ref'] = drive_ref

        # Drive serial number and WWN
        serial_number = enriched_item.get('serialNumber')
        if serial_number:
            enriched_item['drive_serial'] = serial_number

        wwn = enriched_item.get('worldWideName')
        if wwn:
            enriched_item['drive_wwn'] = wwn

        # === PHYSICAL LOCATION ===
        # Slot information (already in model, but ensure it's available)
        slot = enriched_item.get('slot')
        if slot is not None:
            enriched_item['drive_slot'] = slot

        # Tray reference
        physical_location = enriched_item.get('physicalLocation', {})
        if isinstance(physical_location, dict):
            tray_ref = physical_location.get('trayRef')
            if tray_ref:
                enriched_item['drive_tray_ref'] = tray_ref

        # === POOL ASSIGNMENT ===
        # Volume group (storage pool) reference
        volume_group_ref = enriched_item.get('currentVolumeGroupRef')
        LOG.debug(f"Drive enrichment - drive has currentVolumeGroupRef: {volume_group_ref}")
        if volume_group_ref:
            enriched_item['drive_pool_ref'] = volume_group_ref
            LOG.debug(f"Drive enrichment - set drive_pool_ref to: {volume_group_ref}")

            # Add pool name if volume_enricher is available
            if self.volume_enricher and hasattr(self.volume_enricher, 'pool_lookup'):
                LOG.debug(f"Drive enrichment - volume_enricher available, pool_lookup has {len(self.volume_enricher.pool_lookup)} pools")
                pool = self.volume_enricher.pool_lookup.get(volume_group_ref)
                if pool:
                    pool_name = pool.get('name') or pool.get('label')
                    LOG.debug(f"Drive enrichment - found pool with name: {pool_name}")
                    if pool_name:
                        enriched_item['pool_name'] = pool_name
                        LOG.debug(f"Drive enrichment - set pool_name to: {pool_name}")
                    else:
                        LOG.debug(f"Drive enrichment - pool found but no name/label available")
                else:
                    LOG.debug(f"Drive enrichment - pool {volume_group_ref} not found in pool_lookup")
                    LOG.debug(f"Drive enrichment - available pool IDs: {list(self.volume_enricher.pool_lookup.keys())}")
            else:
                LOG.debug(f"Drive enrichment - volume_enricher not available or no pool_lookup")
        else:
            LOG.debug(f"Drive enrichment - no currentVolumeGroupRef found, drive not assigned to pool")

        # === DRIVE CHARACTERISTICS ===
        # Drive type and media
        drive_media_type = enriched_item.get('driveMediaType')
        if drive_media_type:
            enriched_item['drive_type'] = drive_media_type.lower()

        phy_drive_type = enriched_item.get('phyDriveType')
        if phy_drive_type:
            enriched_item['drive_physical_type'] = phy_drive_type.lower()

        # Capacity information
        raw_capacity = enriched_item.get('rawCapacity')
        if raw_capacity:
            try:
                capacity_gb = int(raw_capacity) // (1024**3)
                enriched_item['drive_capacity_gb'] = capacity_gb
            except (ValueError, TypeError):
                pass

        usable_capacity = enriched_item.get('usableCapacity')
        if usable_capacity:
            try:
                usable_gb = int(usable_capacity) // (1024**3)
                enriched_item['drive_usable_capacity_gb'] = usable_gb
            except (ValueError, TypeError):
                pass

        # === DRIVE STATUS ===
        # Drive status and health
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item['drive_status'] = status
            enriched_item['drive_health'] = self.status_map.get(status, 'unknown')

        # Hot spare status
        hot_spare = enriched_item.get('hotSpare')
        if hot_spare is not None:
            enriched_item['drive_hot_spare'] = hot_spare

        # Security and protection
        fde_enabled = enriched_item.get('fdeEnabled')
        if fde_enabled is not None:
            enriched_item['drive_fde_enabled'] = fde_enabled

        security_type = enriched_item.get('driveSecurityType')
        if security_type:
            enriched_item['drive_security_type'] = security_type

        return enriched_item

    def _enrich_host_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich host and host group configuration data.

        Focus on host identity, group membership, and initiator info.
        """
        # === HOST IDENTITY ===
        host_ref = (enriched_item.get('hostRef') or
                   enriched_item.get('id') or
                   enriched_item.get('ref'))
        if host_ref:
            enriched_item['host_id'] = host_ref
            enriched_item['host_ref'] = host_ref

        # Host name/label
        host_name = enriched_item.get('label') or enriched_item.get('name')
        if host_name:
            enriched_item['host_name'] = host_name

        # === HOST TYPE AND OS ===
        # Host type (affects driver and optimization)
        host_type_index = enriched_item.get('hostTypeIndex')
        if host_type_index is not None:
            enriched_item['host_type_index'] = host_type_index

            # Map index to human-readable host type information
            host_type_info = self.host_type_map.get(host_type_index)
            if host_type_info:
                enriched_item['host_type_name'] = host_type_info['name']
                enriched_item['host_os'] = host_type_info['os']
                enriched_item['host_category'] = host_type_info['category']
                LOG.debug(f"Mapped hostTypeIndex {host_type_index} to {host_type_info['name']} ({host_type_info['os']})")
            else:
                # Unknown index - mark as unknown
                enriched_item['host_type_name'] = 'Unknown'
                enriched_item['host_os'] = 'unknown'
                enriched_item['host_category'] = 'unknown'
                LOG.debug(f"Unknown hostTypeIndex {host_type_index} - marked as unknown")

        # Fallback: try to get OS info from hostType object (legacy support)
        if 'host_os' not in enriched_item:
            host_type_obj = enriched_item.get('hostType', {})
            if isinstance(host_type_obj, dict):
                os_name = host_type_obj.get('name', '').lower()
                if 'linux' in os_name:
                    enriched_item['host_os'] = 'linux'
                elif 'windows' in os_name:
                    enriched_item['host_os'] = 'windows'
                elif 'vmware' in os_name:
                    enriched_item['host_os'] = 'vmware'
                elif 'aix' in os_name:
                    enriched_item['host_os'] = 'aix'
                else:
                    enriched_item['host_os'] = 'other'

        # === GROUP MEMBERSHIP ===
        # Host group assignment
        cluster_ref = enriched_item.get('clusterRef')
        if cluster_ref:
            enriched_item['host_group_ref'] = cluster_ref
            enriched_item['host_clustered'] = 'true'

            # Look up hostgroup name for additional tag
            if self.volume_enricher and hasattr(self.volume_enricher, 'hostgroup_lookup'):
                hostgroup = self.volume_enricher.hostgroup_lookup.get(cluster_ref)
                if hostgroup:
                    hostgroup_name = hostgroup.get('label', hostgroup.get('name', 'unknown'))
                    if hostgroup_name and hostgroup_name != 'unknown':
                        enriched_item['hostgroup_name'] = hostgroup_name
                        LOG.debug(f"Host {host_name} belongs to hostgroup {hostgroup_name} ({cluster_ref})")
        else:
            enriched_item['host_clustered'] = 'false'

        # === INITIATOR INFORMATION ===
        # Initiator count and types
        initiators = enriched_item.get('initiators', [])
        if isinstance(initiators, list):
            enriched_item['host_initiator_count'] = len(initiators)

            # Analyze initiator types
            initiator_types = set()
            for initiator in initiators:
                if isinstance(initiator, dict):
                    itype = initiator.get('initiatorType', '').lower()
                    if itype:
                        initiator_types.add(itype)

            if initiator_types:
                if len(initiator_types) == 1:
                    enriched_item['host_initiator_type'] = list(initiator_types)[0]
                else:
                    enriched_item['host_initiator_type'] = 'mixed'

        # === PORT CONNECTIVITY ===
        # Host port information
        host_ports = enriched_item.get('hostSidePorts', [])
        if isinstance(host_ports, list):
            enriched_item['host_port_count'] = len(host_ports)

        return enriched_item

    def _enrich_controller_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich controller configuration data.

        Focus on controller identity, hardware specs, and status.
        """
        # === CONTROLLER IDENTITY ===
        controller_ref = (enriched_item.get('controllerRef') or
                         enriched_item.get('id') or
                         enriched_item.get('ref'))
        if controller_ref:
            enriched_item['controller_id'] = controller_ref
            enriched_item['controller_ref'] = controller_ref

            # Add controller_unit (A/B designation) based on controller ID
            LOG.debug(f"Controller config enrichment starting - controller_ref: {controller_ref}")
            controller_unit = self._get_controller_unit(controller_ref, enriched_item)
            enriched_item['controller_unit'] = controller_unit
            LOG.debug(f"Controller config enrichment - assigned controller_unit: {controller_unit}")

        # Controller model and manufacturer
        model_name = enriched_item.get('modelName')
        if model_name:
            enriched_item['model_name'] = model_name

        manufacturer = enriched_item.get('manufacturer')
        if manufacturer:
            enriched_item['manufacturer'] = manufacturer

        # === HARDWARE SPECIFICATIONS ===
        # Memory specifications
        cache_memory = enriched_item.get('cacheMemorySize')
        if cache_memory is not None:
            enriched_item['cache_memory_size'] = cache_memory

        flash_cache_memory = enriched_item.get('flashCacheMemorySize')
        if flash_cache_memory is not None:
            enriched_item['flash_cache_memory_size'] = flash_cache_memory

        # === IDENTIFICATION ===
        # Serial and part numbers
        serial_number = enriched_item.get('serialNumber')
        if serial_number:
            enriched_item['serial_number'] = serial_number

        part_number = enriched_item.get('partNumber')
        if part_number:
            enriched_item['part_number'] = part_number

        # === STATUS ===
        # Controller status
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item['status'] = status
            enriched_item['controller_status'] = status
            enriched_item['controller_health'] = self.status_map.get(status, 'unknown')

        # Active status
        active = enriched_item.get('active')
        if active is not None:
            enriched_item['active'] = active

        return enriched_item

    def _get_controller_unit(self, controller_id: str, enriched_item: Optional[Dict[str, Any]] = None) -> str:
        """Get controller unit designation (A/B) based on controller ID."""
        LOG.debug(f"_get_controller_unit called with controller_id: '{controller_id}', enriched_item available: {enriched_item is not None}")

        if not controller_id:
            LOG.debug("Controller ID is None/empty, returning 'unknown'")
            return 'unknown'

        # First, try to get the label from physicalLocation (API provides A/B directly)
        if enriched_item:
            physical_location = enriched_item.get('physicalLocation', {})
            LOG.debug(f"physicalLocation found: {physical_location}")
            if isinstance(physical_location, dict):
                api_label = physical_location.get('label')
                LOG.debug(f"API label from physicalLocation: {api_label}")
                if api_label and api_label in ['A', 'B']:
                    LOG.debug(f"Using API label from physicalLocation: {api_label}")
                    return api_label

        # Use the same pattern logic as controller enrichment
        # Controllers ending with '00000001' are A, '00000002' are B
        LOG.debug(f"Checking controller ID pattern for: {controller_id}")
        if controller_id.endswith('00000001'):
            LOG.debug(f"Controller ID {controller_id} ends with '00000001', returning 'A'")
            return 'A'
        elif controller_id.endswith('00000002'):
            LOG.debug(f"Controller ID {controller_id} ends with '00000002', returning 'B'")
            return 'B'
        else:
            # Fallback to simple pattern
            LOG.debug(f"Controller ID {controller_id} doesn't match E-Series pattern, trying simple pattern")
            if controller_id.endswith('1'):
                LOG.debug(f"Controller ID {controller_id} ends with '1' (fallback), returning 'A'")
                return 'A'
            elif controller_id.endswith('2'):
                LOG.debug(f"Controller ID {controller_id} ends with '2' (fallback), returning 'B'")
                return 'B'
            else:
                LOG.debug(f"Controller ID {controller_id} doesn't match any pattern, returning 'unknown'")
                return 'unknown'

    def _enrich_hostgroup_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich host group (cluster) configuration data.

        Focus on group identity and configuration settings.
        """
        # === HOST GROUP IDENTITY ===
        hostgroup_ref = (enriched_item.get('clusterRef') or
                        enriched_item.get('id') or
                        enriched_item.get('ref'))
        if hostgroup_ref:
            enriched_item['hostgroup_id'] = hostgroup_ref
            enriched_item['hostgroup_ref'] = hostgroup_ref

        # Host group name/label
        hostgroup_name = enriched_item.get('label') or enriched_item.get('name')
        if hostgroup_name:
            enriched_item['hostgroup_name'] = hostgroup_name

        # === CONFIGURATION SETTINGS ===
        # Storage array control
        sa_controlled = enriched_item.get('isSAControlled')
        if sa_controlled is not None:
            enriched_item['hostgroup_sa_controlled'] = sa_controlled

        # LUN mapping confirmation
        confirm_lun_mapping = enriched_item.get('confirmLUNMappingCreation')
        if confirm_lun_mapping is not None:
            enriched_item['hostgroup_confirm_lun_mapping'] = confirm_lun_mapping

        # Protection information settings
        pi_capable = enriched_item.get('protectionInformationCapableAccessMethod')
        if pi_capable is not None:
            enriched_item['hostgroup_pi_capable'] = pi_capable

        # LUN 0 restriction
        lun0_restricted = enriched_item.get('isLun0Restricted')
        if lun0_restricted is not None:
            enriched_item['hostgroup_lun0_restricted'] = lun0_restricted

        # === MEMBER INFORMATION ===
        # Cross-reference with host data to find group members
        if self.volume_enricher and hasattr(self.volume_enricher, 'host_lookup'):
            member_hosts = []
            for host_id, host in self.volume_enricher.host_lookup.items():
                if isinstance(host, dict) and host.get('clusterRef') == hostgroup_ref:
                    host_name = host.get('label', host.get('name', 'unknown'))
                    if host_name and host_name != 'unknown':
                        member_hosts.append(host_name)

            # Sort member list for consistent output
            member_hosts.sort()

            # Add member count and comma-delimited member list
            enriched_item['hostgroup_member_count'] = len(member_hosts)
            enriched_item['hostgroup_members'] = ','.join(member_hosts) if member_hosts else ''

            LOG.debug(f"Hostgroup {hostgroup_name} ({hostgroup_ref}) has {len(member_hosts)} members: {member_hosts}")
        else:
            # Fallback if cross-referencing not available
            enriched_item['hostgroup_member_count'] = 0
            enriched_item['hostgroup_members'] = ''
            LOG.debug(f"Cross-referencing not available for hostgroup {hostgroup_name}")

        return enriched_item

    def _enrich_ethernet_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich ethernet/network interface configuration data.

        Focus on network connectivity and interface characteristics.
        """
        # === INTERFACE IDENTITY ===
        interface_ref = (enriched_item.get('interfaceRef') or
                        enriched_item.get('id') or
                        enriched_item.get('ref'))
        if interface_ref:
            enriched_item['interface_id'] = interface_ref

        # === NETWORK CONFIGURATION ===
        # IP address information
        ipv4_config = enriched_item.get('ipv4Config', {})
        if isinstance(ipv4_config, dict):
            ip_address = ipv4_config.get('ipAddress')
            if ip_address:
                enriched_item['interface_ip_address'] = ip_address

            # IP configuration method
            config_method = ipv4_config.get('configMethod', '').lower()
            if config_method:
                enriched_item['interface_ip_method'] = config_method

        # === LINK CHARACTERISTICS ===
        # Link speed and state
        link_speed = enriched_item.get('linkSpeed')
        if link_speed:
            enriched_item['interface_speed'] = link_speed

        link_state = enriched_item.get('linkState', '').lower()
        if link_state:
            enriched_item['interface_state'] = link_state

        # === INTERFACE TYPE ===
        # Check nested ioInterfaceTypeData first (for SAS, iSCSI, IB, etc.)
        io_interface_data = enriched_item.get('ioInterfaceTypeData', {})
        if isinstance(io_interface_data, dict):
            interface_type = io_interface_data.get('interfaceType', '').lower()
            if interface_type:
                enriched_item['interface_type'] = interface_type

        # Fallback to direct interfaceType field if nested lookup didn't work
        if not enriched_item.get('interface_type'):
            interface_type = enriched_item.get('interfaceType', '').lower()
            if interface_type:
                enriched_item['interface_type'] = interface_type

        # Special handling for ethernet interfaces (they might not have ioInterfaceTypeData)
        if not enriched_item.get('interface_type'):
            # Check if this is an ethernet interface by presence of ethernet-specific fields
            if enriched_item.get('macAddr') or enriched_item.get('ipv4Address'):
                enriched_item['interface_type'] = 'ethernet'

        return enriched_item

    def _enrich_interface_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich storage service interface configuration data.

        Handles SAS, iSCSI, IB, and other storage service interfaces.
        This is separate from ethernet management interfaces.
        """
        # === INTERFACE IDENTITY ===
        interface_ref = (enriched_item.get('interfaceRef') or
                        enriched_item.get('id') or
                        enriched_item.get('ref'))
        if interface_ref:
            enriched_item['interface_id'] = interface_ref
            enriched_item['interface_ref'] = interface_ref

        # Controller association
        controller_ref = enriched_item.get('controllerRef')
        if controller_ref:
            enriched_item['controller_ref'] = controller_ref

            # Map controller reference to unit name for human readability
            if controller_ref.endswith('00000001'):
                enriched_item['controller_unit'] = 'A'
            elif controller_ref.endswith('00000002'):
                enriched_item['controller_unit'] = 'B'

        # === INTERFACE TYPE (STORAGE SERVICE INTERFACES) ===
        # Check nested ioInterfaceTypeData first (for SAS, iSCSI, IB, etc.)
        io_interface_data = enriched_item.get('ioInterfaceTypeData', {})
        if isinstance(io_interface_data, dict):
            interface_type = io_interface_data.get('interfaceType', '').lower()
            if interface_type:
                enriched_item['interface_type'] = interface_type

        # Fallback to direct interfaceType field if nested lookup didn't work
        if not enriched_item.get('interface_type'):
            interface_type = enriched_item.get('interfaceType', '').lower()
            if interface_type:
                enriched_item['interface_type'] = interface_type

        # === INTERFACE STATUS ===
        # Interface operational status
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item['interface_status'] = status

        # Link state for connectivity monitoring
        link_state = enriched_item.get('linkStatus', '').lower()
        if link_state:
            enriched_item['interface_link_status'] = link_state

        return enriched_item

    def _enrich_snapshot_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich snapshot configuration data.

        Focus on snapshot identity, base volume, and state.
        """
        # === SNAPSHOT IDENTITY ===
        snapshot_ref = (enriched_item.get('pitRef') or
                       enriched_item.get('id') or
                       enriched_item.get('ref'))
        if snapshot_ref:
            enriched_item['snapshot_id'] = snapshot_ref
            enriched_item['snapshot_ref'] = snapshot_ref

        # Snapshot name/label
        snapshot_name = enriched_item.get('label') or enriched_item.get('name')
        if snapshot_name:
            enriched_item['snapshot_name'] = snapshot_name

        # === BASE VOLUME REFERENCE ===
        # Source volume for the snapshot
        base_volume_ref = enriched_item.get('baseVolumeRef')
        if base_volume_ref:
            enriched_item['snapshot_base_volume'] = base_volume_ref

        # === SNAPSHOT CHARACTERISTICS ===
        # Creation timestamp
        creation_time = enriched_item.get('creationTime')
        if creation_time:
            enriched_item['snapshot_creation_time'] = creation_time

        # Snapshot status
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item['snapshot_status'] = status
            enriched_item['snapshot_health'] = self.status_map.get(status, 'unknown')

        return enriched_item

    def _enrich_hardware_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich hardware component configuration data.

        Focus on component identity and basic characteristics.
        """
        # === COMPONENT IDENTITY ===
        component_ref = (enriched_item.get('componentRef') or
                        enriched_item.get('id') or
                        enriched_item.get('ref'))
        if component_ref:
            enriched_item['hardware_component_id'] = component_ref

        # Component type
        component_type = enriched_item.get('componentType', '').lower()
        if component_type:
            enriched_item['hardware_component_type'] = component_type

        # === LOCATION INFORMATION ===
        # Physical location
        location = enriched_item.get('location')
        if location:
            enriched_item['hardware_location'] = location

        # === STATUS ===
        # Component status
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item['hardware_status'] = status
            enriched_item['hardware_health'] = self.status_map.get(status, 'unknown')

        return enriched_item

    def _enrich_system_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Enrich system-level configuration data.

        Focus on system identity and high-level settings.
        """
        # System name is often already handled by base enricher
        # Add any system-specific enrichments here

        # System model information
        model = enriched_item.get('model')
        if model:
            enriched_item['system_model'] = model

        # Firmware version
        firmware = enriched_item.get('fwVersion')
        if firmware:
            enriched_item['system_firmware'] = firmware

        return enriched_item

    def _enrich_generic_config(self, enriched_item: Dict[str, Any], config_type: str) -> Dict[str, Any]:
        """
        Generic enrichment for unknown or unspecified config types.

        Provides basic standardization without type-specific logic.
        """
        # Generic ID field handling
        generic_id = (enriched_item.get('id') or
                     enriched_item.get('ref') or
                     enriched_item.get('objectId'))
        if generic_id:
            enriched_item[f'{config_type}_id'] = generic_id

        # Generic name field handling
        generic_name = (enriched_item.get('label') or
                       enriched_item.get('name'))
        if generic_name:
            enriched_item[f'{config_type}_name'] = generic_name

        # Generic status handling
        status = enriched_item.get('status', '').lower()
        if status:
            enriched_item[f'{config_type}_status'] = status
            enriched_item[f'{config_type}_health'] = self.status_map.get(status, 'unknown')

        LOG.debug(f"Applied generic enrichment to {config_type}")
        return enriched_item

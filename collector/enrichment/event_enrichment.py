#!/usr/bin/env python3
"""
Event Enrichment for E-Series Performance Analyzer

Enriches event data with alerting metadata for InfluxDB storage and Grafana integration.
This module:
- Adds alert severity levels and tags
- Prepares events for InfluxDB alerting queries
- Supports optional Grafana annotation integration
- Handles deduplication logic for repetitive events
"""

import logging
import json
import hashlib
import time
import requests
from typing import Dict, List, Any, Optional, Union
from .system_identification_helper import SystemIdentificationHelper
from datetime import datetime

from ..schema.base_model import BaseModel
from ..config.endpoint_categories import get_endpoint_category, get_collection_behavior, EndpointCategory

logger = logging.getLogger(__name__)

class EventEnrichment:
    """
    Enriches event data with alerting metadata and handles deduplication.
    """

    # Alert severity mapping for different event types
    ALERT_SEVERITY = {
        'system_failures': 'critical',
        'lockdown_status': 'critical',
        'volume_parity_check_status': 'low',
        'volume_parity_job_check_errors': 'high',
        'data_parity_scan_job_status': 'low',
        'volume_copy_jobs': 'low',
        'volume_copy_job_progress': 'low',
        'drives_erase_progress': 'medium',
        'storage_pools_action_progress': 'low',
        'volume_expansion_progress': 'medium',
    }

    def __init__(self, config: Dict[str, Any], system_enricher=None):
        """
        Initialize event enrichment

        Args:
            config: Configuration dictionary
            system_enricher: SystemEnricher instance for cache-first enrichment
        """
        self.config = config
        self.system_enricher = system_enricher
        self.system_identifier = SystemIdentificationHelper(system_enricher)
        self.enable_deduplication = config.get('enable_event_deduplication', True)
        self.dedup_window_minutes = config.get('event_dedup_window_minutes', 5)

        # Enable Grafana annotations if API token and URL are configured
        self.grafana_api_token = config.get('grafana_api_token')
        self.grafana_api_url = config.get('grafana_api_url')
        self.enable_grafana_annotations = bool(self.grafana_api_token and self.grafana_api_url)

        # In-memory cache for recent event checksums (for deduplication)
        self._recent_events = {}  # {endpoint: {checksum: timestamp}}

        logger.info(f"EventEnrichment initialized: dedup={self.enable_deduplication}, "
                   f"window={self.dedup_window_minutes}min, grafana={self.enable_grafana_annotations}")

    def enrich_event_data(self, endpoint_name: str, raw_data: List[Any]) -> List[Dict[str, Any]]:
        """
        Enrich event data with alerting metadata

        Args:
            endpoint_name: Name of the event endpoint
            raw_data: Raw event data from API (may contain BaseModel instances)
            system_info: System information for tagging

        Returns:
            List of enriched event records ready for InfluxDB
        """
        if not raw_data:
            return []

        # Convert BaseModel objects to dictionaries for JSON serialization
        serializable_data = []
        for item in raw_data:
            try:
                # Check for BaseModel objects (more robust detection)
                if hasattr(item, '__class__') and 'BaseModel' in str(type(item).__mro__):
                    # This is a BaseModel - try different conversion methods
                    if hasattr(item, 'model_dump'):
                        # Pydantic v2 BaseModel
                        serializable_data.append(item.model_dump())
                    elif hasattr(item, 'dict'):
                        # Pydantic v1 BaseModel
                        serializable_data.append(item.dict())
                    elif hasattr(item, '_raw_data'):
                        # Our BaseModel with raw data
                        serializable_data.append(item._raw_data)
                    elif hasattr(item, '__dict__'):
                        # Fallback to __dict__
                        serializable_data.append(item.__dict__)
                    else:
                        logger.warning(f"BaseModel object {type(item)} has no known conversion method")
                        continue
                elif isinstance(item, dict):
                    # Already a dictionary
                    serializable_data.append(item)
                else:
                    # Try to convert to dict if possible
                    try:
                        serializable_data.append(dict(item))
                    except (TypeError, ValueError):
                        logger.warning(f"Unable to serialize event item of type {type(item)}, skipping")
                        continue
            except Exception as e:
                logger.warning(f"Error processing event item {type(item)}: {e}")
                continue

        # Check if this is a duplicate event (if deduplication enabled)
        if self.enable_deduplication and self._is_duplicate_event(endpoint_name, serializable_data):
            logger.debug(f"Skipping duplicate event for {endpoint_name}")
            return []

        enriched_records = []
        current_time = int(time.time())

        for event_item in serializable_data:
            # Get system information from event data using proper identification
            system_config = None
            if 'system_id' in event_item:
                # Try to get system config if system_id is present in event
                temp_data = {'system_id': event_item['system_id']}
                system_config = self.system_identifier.get_system_config_for_performance_data(temp_data)

            if system_config:
                system_name = system_config.get('name')
                system_wwn = system_config.get('wwn')
                system_id = system_config.get('wwn')
            else:
                # If no system config found, this event cannot be properly enriched
                logger.warning(f"No system config found for event {endpoint_name} - skipping enrichment")
                system_name = None
                system_wwn = None
                system_id = None

            # Create enriched record with alert metadata
            enriched_record = {
                # Original event data
                **event_item,

                # Override system identification (fixing any placeholders)
                'system_id': system_id,
                'system_wwn': system_wwn,
                'system_name': system_name,
                'storage_system_name': system_name,  # Override placeholder with enriched name
                'storage_system_wwn': system_wwn,    # Add standardized WWN field

                # Alert metadata
                'alert_type': endpoint_name,
                'alert_severity': self.ALERT_SEVERITY.get(endpoint_name, 'medium'),
                'alert_timestamp': current_time,

                # Event categorization
                'event_category': 'system_event',
                'source': 'eseries_api',

                # For InfluxDB measurement routing
                'measurement_type': 'alert',
            }

            enriched_records.append(enriched_record)

        # Optional: Generate Grafana annotation
        if self.enable_grafana_annotations and system_config:
            self._create_grafana_annotation(endpoint_name, serializable_data, system_config)

        logger.info(f"Enriched {len(enriched_records)} {endpoint_name} events for system {system_name or 'unknown_system'}")
        return enriched_records

    def _is_duplicate_event(self, endpoint_name: str, raw_data: List[Dict[str, Any]]) -> bool:
        """
        Check if this event data is a duplicate of recent data

        Args:
            endpoint_name: Name of the event endpoint
            raw_data: Raw event data to check

        Returns:
            True if this is a duplicate within the deduplication window
        """
        # Generate checksum for the event data
        data_str = json.dumps(raw_data, sort_keys=True)
        checksum = hashlib.md5(data_str.encode('utf-8')).hexdigest()

        current_time = time.time()

        # Clean up old entries beyond the deduplication window
        cutoff_time = current_time - (self.dedup_window_minutes * 60)
        if endpoint_name in self._recent_events:
            self._recent_events[endpoint_name] = {
                cs: ts for cs, ts in self._recent_events[endpoint_name].items()
                if ts > cutoff_time
            }

        # Check if we've seen this checksum recently
        if endpoint_name in self._recent_events:
            if checksum in self._recent_events[endpoint_name]:
                return True  # Duplicate found

        # Store this checksum with current timestamp
        if endpoint_name not in self._recent_events:
            self._recent_events[endpoint_name] = {}
        self._recent_events[endpoint_name][checksum] = current_time

        return False

    def _create_grafana_annotation(self, endpoint_name: str, raw_data: List[Dict[str, Any]],
                                  system_config: Dict[str, Any]):
        """
        Create Grafana annotation for this event (if enabled)

        Args:
            endpoint_name: Name of the event endpoint
            raw_data: Raw event data
            system_config: System configuration
        """
        if not self.enable_grafana_annotations:
            return

        annotation = {
            'time': int(time.time() * 1000),  # Grafana expects milliseconds
            'text': f"E-Series Event: {endpoint_name} - {len(raw_data)} items on {system_config.get('name')}",
            'tags': ['eseries-alert', endpoint_name, system_config.get('name'), 'automated'],
        }

        # Post to Grafana API
        try:
            self._post_grafana_annotation(annotation)
            logger.debug(f"Grafana annotation posted: {endpoint_name}")
        except Exception as e:
            logger.warning(f" Failed to post Grafana annotation for {endpoint_name}: {e}")

    def _post_grafana_annotation(self, annotation: Dict[str, Any]):
        """
        Post annotation to Grafana API

        Args:
            annotation: Annotation data to post
        """
        if not self.grafana_api_url or not self.grafana_api_token:
            logger.debug("Grafana API not configured, skipping annotation")
            return

        url = f"{self.grafana_api_url.rstrip('/')}/api/annotations"
        headers = {
            'Authorization': f'Bearer {self.grafana_api_token}',
            'Content-Type': 'application/json'
        }

        try:
            response = requests.post(url, json=annotation, headers=headers, timeout=10)
            response.raise_for_status()
            logger.debug(f"Grafana annotation posted successfully: {response.status_code}")
        except requests.exceptions.Timeout:
            logger.warning("Timeout posting Grafana annotation")
            raise
        except requests.exceptions.RequestException as e:
            logger.warning(f"Grafana API error: {e}")
            raise

    def get_alert_summary(self) -> Dict[str, Any]:
        """
        Get summary of recent alert activity

        Returns:
            Dictionary with alert statistics
        """
        total_endpoints = len(self._recent_events)
        total_recent_events = sum(len(checksums) for checksums in self._recent_events.values())

        return {
            'total_alert_endpoints': total_endpoints,
            'total_recent_events': total_recent_events,
            'deduplication_enabled': self.enable_deduplication,
            'dedup_window_minutes': self.dedup_window_minutes
        }

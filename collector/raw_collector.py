#!/usr/bin/env python3
"""
Raw API Data Collector for E-Series Performance Analyzer

This module handles collection of raw API responses for offline analysis.
Separate from the main application's enrichment pipeline.

Key features:
- Collects pure API responses without enrichment
- Handles ID-dependent endpoints (requires parent object IDs)
- Smart filename generation with categories
- Self-contained session management
- Single-threaded, simple loop design
"""

import json
import os
import time
import logging
import requests
import urllib3
from datetime import datetime
from typing import Dict, Any, List, Optional

# Import shared config (handle both module and standalone execution)
try:
    # When run as module: python -m collector.raw_collector_cli
    from .config.endpoint_categories import ENDPOINT_CATEGORIES, EndpointCategory, get_measurement_name
    from .config.api_endpoints import API_ENDPOINTS, ID_DEPENDENCIES
except ImportError:
    # When run standalone from collector directory
    from config.endpoint_categories import ENDPOINT_CATEGORIES, EndpointCategory, get_measurement_name
    from config.api_endpoints import API_ENDPOINTS, ID_DEPENDENCIES

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RawApiCollector:
    """
    Raw API response collector for E-Series systems
    """

    def __init__(self, base_url: str, username: str, password: str, output_dir: str, system_id: Optional[str] = None):
        """
        Initialize the raw API collector

        Args:
            base_url: E-Series API base URL (e.g., 'https://10.1.2.3:8443')
            username: API username
            password: API password
            output_dir: Directory for JSON output files
            system_id: Optional system ID (will be discovered if not provided)
        """
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.output_dir = output_dir
        self.system_id = system_id
        self.session: Optional[requests.Session] = None


        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # Cache for parent objects (for ID-dependent endpoints)
        self.parent_cache = {}

    def connect(self) -> bool:
        """Establish API session with authentication.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Create session with TLS configuration (disable SSL warnings for dev)
            self.session = requests.Session()
            self.session.verify = False  # For development with self-signed certificates

            # Test basic connectivity
            test_url = f"{self.base_url}/devmgr/v2/storage-systems"
            response = self.session.get(test_url, timeout=10)

            # If we get any response (even 401), the endpoint is reachable
            logger.info(f"Successfully connected to SANtricity endpoint: {self.base_url}")

            # Perform login to get session cookies
            login_url = f"{self.base_url}/devmgr/utils/login"
            login_data = {
                'userId': self.username,
                'password': self.password
            }

            login_response = self.session.post(login_url, json=login_data, timeout=10)
            login_response.raise_for_status()

            logger.info(f"Successfully authenticated with SANtricity API")

            # Auto-discover system ID if not provided
            if not self.system_id:
                systems_response = self.session.get(test_url, timeout=10)
                systems_response.raise_for_status()
                systems = systems_response.json()

                if systems and len(systems) > 0:
                    self.system_id = systems[0].get('wwn')
                    system_name = systems[0].get('name', 'Unknown')
                    logger.info(f"Auto-discovered system: {system_name} (WWN: {self.system_id})")
                else:
                    logger.error("No storage systems found")
                    return False

            return True

        except Exception as e:
            logger.error(f"Failed to connect to SANtricity API: {e}")
            if self.session:
                self.session.close()
                self.session = None
            return False

    def initialize_writer(self):
        """Initialize JSON writing capability"""
        logger.info(f"Raw collector initialized for writing to: {self.output_dir}")
        logger.info(f"System ID: {self.system_id}")
        # Create output directory if it doesn't exist
        os.makedirs(self.output_dir, exist_ok=True)

    def _write_json_files(self, writer_data: Dict[str, Any]) -> bool:
        """Write JSON files using centralized configuration

        Args:
            writer_data: Dictionary with endpoint data and metadata

        Returns:
            True if successful, False otherwise
        """
        try:
            timestamp = writer_data.get('timestamp')

            for endpoint_name, data in writer_data.get('endpoints', {}).items():
                if not data:  # Skip empty data
                    continue

                # Use centralized config for filename
                measurement_name = get_measurement_name(endpoint_name)
                filename = f"{measurement_name}_{self.system_id}_{timestamp}.json"
                filepath = os.path.join(self.output_dir, filename)

                # Create file content with metadata
                file_content = {
                    'system_id': self.system_id,
                    'timestamp': timestamp,
                    'endpoint': endpoint_name,
                    'measurement_name': measurement_name,
                    'data': data
                }

                # Write JSON file
                with open(filepath, 'w') as f:
                    json.dump(file_content, f, indent=2, default=str)

                logger.debug(f"Wrote {endpoint_name} data to {filename}")

            return True

        except Exception as e:
            logger.error(f"Failed to write JSON files: {e}")
            return False

    def _call_api(self, endpoint_key: str, object_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Make API call to specified endpoint

        Args:
            endpoint_key: Key from API_ENDPOINTS mapping
            object_id: Optional object ID for ID-dependent endpoints

        Returns:
            JSON response or None if failed
        """
        if endpoint_key not in API_ENDPOINTS:
            logger.warning(f"Unknown endpoint: {endpoint_key}")
            return None

        try:
            # Build URL
            endpoint_path = API_ENDPOINTS[endpoint_key]
            if object_id:
                endpoint_path = endpoint_path.format(system_id=self.system_id, id=object_id)
            else:
                endpoint_path = endpoint_path.format(system_id=self.system_id)

            url = f"{self.base_url}/{endpoint_path}"

            # Make request
            if not self.session:
                raise RuntimeError("Not connected - call connect() first")
            response = self.session.get(url)
            response.raise_for_status()

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.warning(f"API call failed for {endpoint_key}: {e}")
            return None

    def collect_endpoint(self, endpoint_key: str) -> bool:
        """
        Collect data from a single endpoint (handling ID dependencies)

        Args:
            endpoint_key: Endpoint to collect from

        Returns:
            True if collection successful, False otherwise
        """
        try:
            # Check if this endpoint requires ID dependency
            if endpoint_key in ID_DEPENDENCIES:
                return self._collect_id_dependent_endpoint(endpoint_key)
            else:
                return self._collect_simple_endpoint(endpoint_key)

        except Exception as e:
            logger.error(f"Failed to collect {endpoint_key}: {e}")
            return False

    def _collect_simple_endpoint(self, endpoint_key: str) -> bool:
        """Collect from endpoint that doesn't require IDs"""
        data = self._call_api(endpoint_key)
        if data is not None:
            # Write to JSON using internal writer
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M')
            writer_data = {
                'timestamp': timestamp,
                'endpoints': {endpoint_key: data}
            }
            success = self._write_json_files(writer_data)

            if success:
                item_count = len(data) if isinstance(data, list) else 1
                logger.info(f"{endpoint_key}: {item_count} items")
                return True
            else:
                logger.error(f"Failed to write {endpoint_key}")
                return False
        else:
            logger.warning(f"{endpoint_key}: No data")
            return False

    def _collect_id_dependent_endpoint(self, endpoint_key: str) -> bool:
        """Collect from endpoint that requires parent object IDs"""
        dependency = ID_DEPENDENCIES[endpoint_key]
        id_source = dependency['id_source']
        id_field = dependency['id_field']

        # Get parent objects (use cache if available)
        if id_source not in self.parent_cache:
            parent_data = self._call_api(id_source)
            if not parent_data:
                logger.warning(f"{endpoint_key}: Could not get parent data from {id_source}")
                return False
            self.parent_cache[id_source] = parent_data

        parent_objects = self.parent_cache[id_source]
        if not isinstance(parent_objects, list):
            parent_objects = [parent_objects]

        # Collect data for each parent object
        all_data = []
        success_count = 0

        for parent_obj in parent_objects:
            if not isinstance(parent_obj, dict) or id_field not in parent_obj:
                continue

            object_id = parent_obj[id_field]
            data = self._call_api(endpoint_key, object_id)

            if data is not None:
                if isinstance(data, list):
                    all_data.extend(data)
                else:
                    all_data.append(data)
                success_count += 1

        # Write aggregated data
        if all_data:
            timestamp = datetime.utcnow().strftime('%Y%m%d%H%M')
            writer_data = {
                'timestamp': timestamp,
                'endpoints': {endpoint_key: all_data}
            }
            success = self._write_json_files(writer_data)

            if success:
                logger.info(f"{endpoint_key}: {len(all_data)} items from {success_count}/{len(parent_objects)} objects")
                return True
            else:
                logger.error(f"Failed to write {endpoint_key}")
                return False
        else:
            logger.warning(f"{endpoint_key}: No data from any object")
            return False

    def collect_by_category(self, category: EndpointCategory) -> Dict[str, bool]:
        """
        Collect all endpoints for a specific category

        Args:
            category: Category to collect

        Returns:
            Dictionary mapping endpoint names to success status
        """
        endpoints = ENDPOINT_CATEGORIES.get(category, set())
        results = {}

        logger.info(f"Collecting {category.value} endpoints: {len(endpoints)} total")

        for endpoint in endpoints:
            if endpoint in API_ENDPOINTS:
                results[endpoint] = self.collect_endpoint(endpoint)
            else:
                logger.warning(f"Skipping unknown endpoint: {endpoint}")
                results[endpoint] = False

        success_count = sum(1 for success in results.values() if success)
        logger.info(f"{category.value}: {success_count}/{len(endpoints)} endpoints successful")

        return results

    def collect_all(self) -> Dict[str, Dict[str, bool]]:
        """
        Collect all categorized endpoints

        Returns:
            Nested dictionary: {category: {endpoint: success}}
        """
        if not self.session:
            logger.error("Not connected - call connect() first")
            return {}

        logger.info(f"Starting collection for all categories...")
        all_results = {}

        for category in EndpointCategory:
            logger.info(f"\n=== {category.value.upper()} COLLECTION ===")
            category_results = self.collect_by_category(category)
            all_results[category.value] = category_results

            # Log category summary
            success_count = sum(1 for success in category_results.values() if success)
            total_count = len(category_results)
            logger.info(f"{category.value.upper()}: {success_count}/{total_count} endpoints successful")

            # Small delay between categories
            time.sleep(1)

        return all_results

    def disconnect(self):
        """Clean up session"""
        if self.session:
            self.session.close()
            self.session = None
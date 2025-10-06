"""Live API DataSource implementation.

Collects data directly from NetApp E-Series API endpoints.
"""

import logging
import time
import requests
from typing import Dict, List, Any, Optional

from .base import DataSource, CollectionResult, CollectionType, SystemInfo


class LiveAPIDataSource(DataSource):
    """DataSource implementation for live SANtricity API collection.

    This implementation handles:
    - API session management and authentication
    - Direct endpoint data collection
    - System discovery and identification
    - Environmental monitoring via symbols API
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.logger = logging.getLogger(__name__)

        # API connection state
        self.session: Optional[Any] = None  # requests.Session
        self.active_endpoint: Optional[str] = None
        self.active_api_list: List[str] = []
        self.san_headers: Dict[str, str] = {}
        self.system_id: Optional[str] = None
        self.system_name: Optional[str] = None

        # Config scheduler for live API mode
        self.config_scheduler: Optional[Any] = None  # ConfigCollectionScheduler

        # Configuration from app/main.py live API setup
        self.api_endpoints = config.get('api', [])  # Changed from 'api_endpoints' to 'api'
        self.username = config.get('username')
        self.password = config.get('password')
        self.tls_ca = config.get('tls_ca')
        self.tls_validation = config.get('tls_validation', 'strict')

        # Session state
        self.session = None
        self.active_endpoint = None
        self.san_headers = {}

    def _inject_system_info(self, data_list):
        """Inject system WWN and name into each performance/config/event record."""
        if not data_list:
            self.logger.debug("No data list provided for system info injection")
            return

        if not self.system_id:
            self.logger.warning("No system_id available for injection")
            return

        if not self.system_name:
            self.logger.warning(f"No system_name available for injection (system_id: {self.system_id})")
            return

        self.logger.debug(f"Injecting system info: WWN={self.system_id}, Name={self.system_name}")

        for record in data_list:
            if isinstance(record, dict):
                # Inject system identification fields - standardized on system_id
                record['system_id'] = self.system_id
                record['storage_system_name'] = self.system_name

        self.logger.debug(f"Injected system info (WWN: {self.system_id}, Name: {self.system_name}) into {len(data_list)} records")

    def initialize(self) -> bool:
        """Initialize live API connection with authentication.

        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # Import required modules
            import requests
            import urllib3

            # Port session establishment
            username = self.config.get('username')
            password = self.config.get('password')
            management_ips = self.config.get('api', [])
            tls_ca = self.config.get('tls_ca')
            tls_validation = self.config.get('tls_validation', 'strict')

            if not username or not password or not management_ips:
                self.logger.error("Username, password, and management IPs required for live API mode")
                return False

            self.logger.info(f"Establishing API session with endpoints: {management_ips}")

            # Create session with TLS configuration
            self.session = requests.Session()

            if tls_validation == 'none':
                # Disable SSL verification and warnings for SANtricity API
                self.session.verify = False
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                self.logger.warning("TLS validation is DISABLED for SANtricity API. This is insecure.")
            elif tls_validation == 'normal':
                # Standard SSL verification
                self.session.verify = tls_ca if tls_ca else True
            elif tls_validation == 'strict':
                # Strict SSL verification (default)
                self.session.verify = tls_ca if tls_ca else True

            # Try to find a working endpoint
            self.active_endpoint = None
            for endpoint in management_ips:
                try:
                    test_endpoint = f"https://{endpoint}:8443"

                    # Test basic connectivity with a simple endpoint
                    test_url = f"{test_endpoint}/devmgr/v2/storage-systems"
                    response = self.session.get(test_url, timeout=10)

                    # If we get any response (even 401), the endpoint is reachable
                    self.logger.info(f"Successfully connected to SANtricity endpoint: {endpoint}")
                    self.active_endpoint = test_endpoint
                    self.active_api_list = [endpoint]
                    break

                except Exception as e:
                    self.logger.debug(f"Failed to connect to {endpoint}: {e}")
                    continue

            if not self.active_endpoint:
                self.logger.error(f"Failed to connect to any SANtricity endpoint: {management_ips}")
                return False

            # Perform initial login (sets session cookies) - from app/main.py get_fresh_token
            self.logger.info(f"Successfully connected to controller at {self.active_endpoint}")

            try:
                # First login to get session
                login_url = f"{self.active_endpoint}/devmgr/utils/login"
                login_payload = {
                    "userId": username,
                    "password": password,
                    "xsrfProtected": False  # Start without XSRF for compatibility
                }

                self.logger.debug(f"Attempting session login to {login_url} with user {username}")
                response = self.session.post(login_url, json=login_payload, timeout=10)

                if response.status_code == 200:
                    self.logger.info("Successfully authenticated with SANtricity API")

                    # Try to get a bearer token (newer SANtricity models)
                    token_url = f"{self.active_endpoint}/devmgr/v2/access-token"
                    token_payload = {"duration": 600}

                    try:
                        self.logger.debug(f"Attempting to get bearer token from {token_url}")
                        token_response = self.session.post(token_url, json=token_payload, timeout=10)

                        if token_response.status_code == 200:
                            token_data = token_response.json()
                            access_token = token_data.get('accessToken')
                            if access_token:
                                self.san_headers = {'Authorization': f'Bearer {access_token}'}
                                self.logger.info(f"Using bearer token authentication (duration: {token_data.get('duration', 'unknown')}s)")
                            else:
                                self.logger.warning("Bearer token response missing accessToken field")
                                self.san_headers = {}  # Use session-based auth
                        else:
                            self.logger.debug(f"Bearer token not available (status {token_response.status_code}), falling back to session-based auth")
                            self.san_headers = {}  # Use session-based auth

                    except Exception as bearer_error:
                        self.logger.debug(f"Bearer token not supported: {bearer_error}, falling back to session-based auth")
                        self.san_headers = {}  # Use session-based auth

                    # Log which authentication method we're using
                    if self.san_headers:
                        self.logger.info("Using bearer token authentication")
                    else:
                        self.logger.info("Using session-based authentication (older SANtricity compatibility)")

                else:
                    self.logger.error(f"Login failed with status {response.status_code}: {response.text}")
                    return False

            except Exception as e:
                self.logger.error(f"Failed to login: {e}")
                return False

            # Get system information - first get all storage systems, then use the first one's WWN
            try:
                # Get list of all storage systems first using proper API endpoint
                systems_url = f"{self.active_endpoint}/devmgr/v2/storage-systems"
                self.logger.debug(f"Requesting storage systems from {systems_url} with authentication headers")
                systems_resp = self.session.get(systems_url, headers=self.san_headers)

                self.logger.debug(f"Storage systems API response: {systems_resp.status_code}")
                systems_resp.raise_for_status()
                systems = systems_resp.json()

                self.logger.debug(f"Found {len(systems) if systems else 0} storage systems")
                if systems:
                    self.logger.debug(f"First system data: {systems[0] if systems else 'None'}")

                if not systems or len(systems) == 0:
                    self.logger.error("No storage systems found")
                    return False

                # Use the first system
                system = systems[0]
                sys_id = system.get("wwn")
                sys_name = system.get("name")

                if not sys_id:
                    self.logger.error("Unable to retrieve system WWN - required for metrics collection")
                    self.logger.debug(f"System data keys: {list(system.keys()) if system else 'No system data'}")
                    return False

                self.logger.info(f"Connected to E-Series system: WWN={sys_id}, Name={sys_name}")
                self._system_info = SystemInfo(wwn=sys_id, name=sys_name)
                self.logger.debug(f"Created SystemInfo object: {self._system_info}")
                self.logger.debug(f"SystemInfo WWN: {self._system_info.wwn}, Name: {self._system_info.name}")

                # Store system info for collector initialization
                self.system_id = sys_id
                self.system_name = sys_name

            except requests.RequestException as req_err:
                self.logger.error(f"Request failed: {req_err}")
                self.logger.debug(f"System retrieval failed - endpoint: {self.active_endpoint}, session active: {self.session is not None}, headers: {bool(self.san_headers)}")
                if hasattr(req_err, 'response') and req_err.response is not None:
                    self.logger.error(f"HTTP {req_err.response.status_code}: {req_err.response.text[:200] if hasattr(req_err.response, 'text') else 'No response text'}")
                return False
            except Exception as e:
                self.logger.error(f"Failed to retrieve system information: {e}")
                self.logger.debug(f"System retrieval failed - endpoint: {self.active_endpoint}, session active: {self.session is not None}, headers: {bool(self.san_headers)}")
                return False

            # Initialize config scheduler for proper config collection scheduling
            interval = self.config.get('interval', 300)
            try:
                from ..config.collection_schedules import ConfigCollectionScheduler
                self.config_scheduler = ConfigCollectionScheduler(interval)
                self.logger.info(f"Initialized config collection scheduler with {interval}s base interval")

                # Log schedule information
                schedule_info = self.config_scheduler.get_schedule_info()
                self.logger.info("Config collection schedule:")
                for freq_name, info in schedule_info.items():
                    self.logger.info(f"  {freq_name}: every {info['multiplier']}x base ({info['effective_interval']}s) - {info['config_types']}")
            except Exception as e:
                self.logger.error(f"Failed to initialize config scheduler: {e}")
                self.config_scheduler = None

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize LiveAPIDataSource: {e}")
            return False

    def collect_performance_data(self) -> CollectionResult:
        """Collect all performance data types from live API."""
        try:
            if not self.session or not self.active_endpoint or not self.system_id:
                return CollectionResult(
                    collection_type=CollectionType.PERFORMANCE,
                    data={},
                    success=False,
                    error_message="API session not initialized"
                )

            # Collect performance data directly from API endpoints
            perf_data = {}

            # Use centralized configuration instead of hardcoded list
            from ..config.endpoint_categories import get_endpoints_by_category, EndpointCategory
            perf_endpoints = get_endpoints_by_category(EndpointCategory.PERFORMANCE)

            for endpoint_key in perf_endpoints:
                try:
                    api_response = self._call_api(endpoint_key)
                    if api_response:
                        # Use centralized naming for consistency with JSON datasource
                        from ..config.endpoint_categories import get_measurement_name
                        measurement_name = get_measurement_name(endpoint_key)

                        # Use shared data extraction utility to handle different analyzed statistics formats
                        from ..utils.data_extraction import extract_analyzed_statistics_data
                        stats_data = extract_analyzed_statistics_data(
                            api_response, endpoint_key, 'live_api', auto_inject_system_context=False
                        )

                        # Inject system information into each record (like JSON replay does)
                        if stats_data:
                            self._inject_system_info(stats_data)
                            perf_data[measurement_name] = stats_data
                            self.logger.debug(f"Collected {measurement_name} data from API: {len(stats_data)} records")

                except Exception as e:
                    self.logger.warning(f"Failed to collect {endpoint_key}: {e}")

            self.logger.info(f"Collected performance data successfully: {list(perf_data.keys())}")

            return CollectionResult(
                collection_type=CollectionType.PERFORMANCE,
                data=perf_data,
                success=True,
                metadata={'source': 'live_api', 'system_id': self.system_id}
            )

        except Exception as e:
            self.logger.error(f"Failed to collect performance data from API: {e}")
            return CollectionResult(
                collection_type=CollectionType.PERFORMANCE,
                data={},
                success=False,
                error_message=str(e)
            )

    def collect_configuration_data(self) -> CollectionResult:
        """Collect all configuration data types from live API."""
        try:
            if not self.session or not self.active_endpoint or not self.system_id:
                return CollectionResult(
                    collection_type=CollectionType.CONFIGURATION,
                    data={},
                    success=False,
                    error_message="API session not initialized"
                )

            if not self.config_scheduler:
                return CollectionResult(
                    collection_type=CollectionType.CONFIGURATION,
                    data={},
                    success=True,
                    metadata={'source': 'live_api', 'status': 'no_scheduler'}
                )

            # Collect configuration data directly from API endpoints
            config_data = {}

            # Use centralized configuration instead of hardcoded list
            from ..config.endpoint_categories import get_endpoints_by_category, EndpointCategory
            config_endpoints = get_endpoints_by_category(EndpointCategory.CONFIGURATION)

            for endpoint_key in config_endpoints:
                try:
                    api_response = self._call_api(endpoint_key)
                    if api_response:
                        # Use centralized naming for consistency with JSON datasource
                        from ..config.endpoint_categories import get_measurement_name
                        measurement_name = get_measurement_name(endpoint_key)

                        # Use shared data extraction utility for configuration data
                        from ..utils.data_extraction import extract_configuration_data
                        config_records = extract_configuration_data(
                            api_response, endpoint_key, 'live_api', auto_inject_system_context=False
                        )

                        # Inject system information into each config record
                        if config_records:
                            self._inject_system_info(config_records)
                            config_data[measurement_name] = config_records
                            self.logger.debug(f"Collected {measurement_name} config from API: {len(config_records)} records")

                except Exception as e:
                    self.logger.warning(f"Failed to collect {endpoint_key}: {e}")

            self.logger.info(f"Collected configuration data successfully: {list(config_data.keys())}")

            return CollectionResult(
                collection_type=CollectionType.CONFIGURATION,
                data=config_data,
                success=True,
                metadata={
                    'source': 'live_api',
                    'system_id': self.system_id,
                    'status': 'success'
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to collect configuration data from API: {e}")
            return CollectionResult(
                collection_type=CollectionType.CONFIGURATION,
                data={},
                success=False,
                error_message=str(e)
            )

    def collect_event_data(self) -> CollectionResult:
        """Collect all event/alert data types from live API."""
        try:
            if not self.session or not self.active_endpoint or not self.system_id:
                return CollectionResult(
                    collection_type=CollectionType.EVENTS,
                    data={},
                    success=False,
                    error_message="API session not initialized"
                )

            # Collect event data directly from API endpoints
            event_data = {}

            # Use centralized configuration instead of hardcoded event structure
            from ..config.endpoint_categories import get_endpoints_by_category, EndpointCategory
            event_endpoints = get_endpoints_by_category(EndpointCategory.EVENTS)

            for endpoint_key in event_endpoints:
                try:
                    api_response = self._call_api(endpoint_key)
                    if api_response:
                        # Use centralized naming for consistency with JSON datasource
                        from ..config.endpoint_categories import get_measurement_name
                        measurement_name = get_measurement_name(endpoint_key)

                        # Convert API response to list format expected by event processing
                        if isinstance(api_response, dict):
                            event_records = [api_response]
                        elif isinstance(api_response, list):
                            event_records = api_response
                        else:
                            event_records = []

                        # Inject system information into each event record
                        if event_records:
                            self._inject_system_info(event_records)
                            event_data[measurement_name] = event_records
                            self.logger.debug(f"Collected {measurement_name} events from API: {len(event_records)} records")

                except Exception as e:
                    self.logger.warning(f"Failed to collect {endpoint_key}: {e}")

            self.logger.info(f"Collected event data successfully: {list(event_data.keys())}")

            return CollectionResult(
                collection_type=CollectionType.EVENTS,
                data=event_data,
                success=True,
                metadata={'source': 'live_api', 'deduplication': True}
            )

        except Exception as e:
            self.logger.error(f"Failed to collect event data: {e}")
            return CollectionResult(
                collection_type=CollectionType.EVENTS,
                data={},
                success=False,
                error_message=str(e)
            )

    def collect_environmental_data(self) -> CollectionResult:
        """Collect environmental monitoring data from live API."""
        try:
            if not self.session or not self.active_endpoint or not self.system_id:
                return CollectionResult(
                    collection_type=CollectionType.ENVIRONMENTAL,
                    data={},
                    success=False,
                    error_message="API session not initialized"
                )

            # Collect environmental data directly from API endpoints
            self.logger.info("Starting environmental monitoring collection from live API...")
            env_start_time = time.time()

            environmental_data = {}

            # Use centralized configuration instead of hardcoded list
            from ..config.endpoint_categories import get_endpoints_by_category, EndpointCategory
            env_endpoints = get_endpoints_by_category(EndpointCategory.ENVIRONMENTAL)

            for endpoint_key in env_endpoints:
                try:
                    api_response = self._call_api(endpoint_key)
                    if api_response and isinstance(api_response, dict):
                        # Use centralized naming for consistency with JSON datasource
                        from ..config.endpoint_categories import get_measurement_name
                        measurement_name = get_measurement_name(endpoint_key)

                        # Convert raw API response to format expected by enrichment pipeline
                        # This matches the conversion done in JSON replay datasource
                        if endpoint_key == 'env_power' and api_response.get('returnCode') == 'ok' and 'energyStarData' in api_response:
                            # Convert to format expected by symbols_collector processing
                            processed_data = {'measurement': 'power', 'data': api_response['energyStarData']}
                            environmental_data[measurement_name] = [processed_data]
                        elif endpoint_key == 'env_temperature' and api_response.get('returnCode') == 'ok' and 'thermalSensorData' in api_response:
                            # Convert to format expected by symbols_collector processing
                            processed_data = {'measurement': 'temp', 'data': api_response['thermalSensorData']}
                            environmental_data[measurement_name] = [processed_data]
                        else:
                            # Fallback: wrap raw response in list format
                            environmental_data[measurement_name] = [api_response]

                        self.logger.debug(f"Collected {measurement_name} environmental data from API")
                except Exception as e:
                    self.logger.warning(f"Failed to collect {endpoint_key}: {e}")

            env_time = time.time() - env_start_time
            total_env_records = len(environmental_data)
            self.logger.info(f"Environmental monitoring collection completed in {env_time:.2f}s, collected {total_env_records} measurements")

            return CollectionResult(
                collection_type=CollectionType.ENVIRONMENTAL,
                data=environmental_data,
                success=True,
                metadata={
                    'source': 'live_api',
                    'collection_time_seconds': env_time,
                    'measurements_collected': len(environmental_data)
                }
            )

        except Exception as e:
            self.logger.error(f"Failed to collect environmental data from API: {e}")
            return CollectionResult(
                collection_type=CollectionType.ENVIRONMENTAL,
                data={},
                success=False,
                error_message=str(e)
            )

    def _call_api(self, endpoint_key: str) -> Dict[str, Any]:
        """Make API call to specified endpoint and return raw JSON response.

        Args:
            endpoint_key: Key from API_ENDPOINTS configuration

        Returns:
            Raw JSON response from API call
        """
        from ..config.api_endpoints import API_ENDPOINTS

        if not self.session or not self.active_endpoint:
            self.logger.error("API session not initialized for endpoint call")
            return {}

        endpoint_template = API_ENDPOINTS.get(endpoint_key)
        if not endpoint_template:
            # Expected endpoints that may not be configured on all systems
            expected_missing = {
                'volume_consistency_group_members', 'volume_consistency_group_config',
                'total_records', 'performance_data', 'status', 'parity_scan_jobs'
            }
            if endpoint_key in expected_missing:
                self.logger.debug(f"Endpoint not configured for this system: {endpoint_key}")
            else:
                self.logger.warning(f"Unknown endpoint key: {endpoint_key}")
            return {}

        # Format endpoint with system_id
        endpoint_url = endpoint_template.format(system_id=self.system_id)
        full_url = f"{self.active_endpoint.replace('/devmgr/v2/storage-systems', '')}/{endpoint_url}"

        try:
            response = self.session.get(full_url, headers=self.san_headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # Expected 404s for optional features
                optional_features = {
                    'ssd_cache': 'SSD cache/flash cache not configured',
                    'mirrors': 'Mirror/remote replication not configured',
                    'flash_cache': 'Flash cache not enabled',
                    'snapshot_groups': 'Snapshot groups not configured',
                    'consistency_groups': 'Consistency groups not configured'
                }
                feature_desc = optional_features.get(endpoint_key, 'Feature not available')
                self.logger.info(f"{endpoint_key}: {feature_desc} (404)")
            else:
                self.logger.error(f"API call failed for {endpoint_key}: HTTP {e.response.status_code}")
            return {}
        except Exception as e:
            self.logger.error(f"API call failed for {endpoint_key}: {e}")
            return {}

    def cleanup(self) -> None:
        """Clean up API session and logout."""
        try:
            if self.session and self.active_endpoint:
                # Port logout logic from app/main.py logout_session function
                try:
                    logout_url = f"{self.active_endpoint}/devmgr/utils/login"
                    response = self.session.delete(logout_url, timeout=5)
                    self.logger.debug(f"Logged out from SANtricity at {self.active_endpoint}")
                except Exception as e:
                    self.logger.debug(f"Logout attempt failed (not critical): {e}")

                # Close the session
                self.session.close()
                self.logger.info("API session closed")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        finally:
            # Reset state
            self.session = None
            self.active_endpoint = None
            self.active_api_list = []
            self.san_headers = {}
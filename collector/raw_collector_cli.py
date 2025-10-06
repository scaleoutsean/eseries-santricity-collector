#!/usr/bin/env python3
"""
CLI for Raw E-Series API Data Collection

Simple command-line interface for collecting raw API responses.
"""

import argparse
import sys
import logging
import time
from pathlib import Path

# Import from local collector modules - handle both module and standalone execution
try:
    # When run as module: python -m collector.raw_collector_cli
    from .raw_collector import RawApiCollector
    from .config.endpoint_categories import EndpointCategory
except ImportError:
    # When run standalone from collector directory: python raw_collector_cli.py
    from raw_collector import RawApiCollector
    from config.endpoint_categories import EndpointCategory

def main():
    parser = argparse.ArgumentParser(
        description='Collect raw API data from E-Series systems using centralized endpoint configuration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
HOW TO RUN:
  From project root directory:
    python -m collector.raw_collector_cli [OPTIONS]
    python3 -m collector.raw_collector_cli [OPTIONS]

  From collector directory:
    python raw_collector_cli.py [OPTIONS]
    python3 raw_collector_cli.py [OPTIONS]

EXAMPLES:
  # Collect all endpoints from one or both controllers (single iteration)
  python -m collector.raw_collector_cli --api 10.1.1.1 10.1.1.2 --user monitor --password admin123 --output ./api_json

  # Collect only performance data with 5 iterations, rotating through 3 APIs
  python3 -m collector.raw_collector_cli --api 10.1.1.1 10.1.1.2 --user monitor --password admin123 --output ./api_json --category performance --iterations 5 --interval 30

  # Collect configuration data from multiple APIs, 10 iterations with 60s intervals (rotates through APIs)
  python3 -m collector.raw_collector_cli --api 10.2.3.4 --user monitor --password admin123 --output ./api_json --category configuration --iterations 10 --interval 60

  # Collect environmental data (power, temperature) from single API
  python3 -m collector.raw_collector_cli --api 10.1.1.1 --user monitor --password admin123 --output ./api_json --category environmental --iterations 5 --interval 60

  # Continuous collection from single API (1000 iterations, 5 minute intervals)
  python3 -m collector.raw_collector_cli --api 10.1.1.1 --user monitor --password admin123 --output ./api_json --iterations 1000 --interval 300

NOTES:
  - Uses centralized filename generation: config_*, performance_*, env_*, events_*
  - Filenames include endpoint name from get_measurement_name() mapping
  - Multiple APIs rotate automatically during multi-iteration collection
  - Output files are timestamped JSON responses ready for JSON replay mode
        """
    )

    parser.add_argument('--api', required=True, nargs='+',
                       help='E-Series management IP addresses (API endpoints). When multiple iterations are specified, each iteration will use a different host in rotation.')
    parser.add_argument('--user', required=True,
                       help='Username for SANtricity Web Services API (e.g., monitor, admin)')
    parser.add_argument('--password', required=True,
                       help='Password')
    parser.add_argument('--output', '-o', default='./api_json',
                       help='Output directory for JSON files (default: ./api_json)')
    parser.add_argument('--system-id',
                       help='Specific system ID/WWN (optional, will auto-detect if not provided)')
    parser.add_argument('--category', choices=[cat.value for cat in EndpointCategory],
                       help='Collect only endpoints from specific category')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose logging')
    parser.add_argument('--iterations', type=int, default=1,
                       help='Number of collection iterations (default: 1)')
    parser.add_argument('--interval', type=int, default=60,
                       help='Interval in seconds between iterations (default: 60)')

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print(f"Collection Plan:")
    print(f"  API endpoints: {', '.join(args.api)}")
    print(f"  Iterations: {args.iterations}")
    if len(args.api) > 1 and args.iterations > 1:
        print(f"  Multi-endpoint rotation: Each iteration will use a different E-Series management endpoint")
    print(f"  interval between iterations: {args.interval}s")
    if args.category:
        print(f"  Category: {args.category}")
    else:
        print(f"  Category: ALL")
    print(f"  Output directory: {args.output}")
    print()

    # Track overall statistics
    overall_stats = {
        'total_iterations': 0,
        'successful_apis': 0,
        'failed_apis': 0,
        'total_endpoints_collected': 0
    }

    try:
        # Main collection loop - iterate over iterations and hosts
        for iteration in range(1, args.iterations + 1):
            time_begin = time.time()
            print(f"=== ITERATION {iteration}/{args.iterations} ===")

            iteration_stats = {
                'successful_apis': 0,
                'failed_apis': 0,
                'total_endpoints': 0
            }

            # Select API endpoint for this iteration (rotate through APIs if multiple iterations)
            if len(args.api) == 1 or args.iterations == 1:
                # Single API or single iteration - use all APIs
                apis_to_process = args.api
            else:
                # Multiple APIs and iterations - rotate through APIs
                api_index = (iteration - 1) % len(args.api)
                apis_to_process = [args.api[api_index]]

            # Loop through selected APIs for this iteration
            for api_idx, api in enumerate(apis_to_process, 1):
                print(f"\n[{iteration}.{api_idx}] Processing API: {api}")

                # Build base URL for current API
                if '://' not in api:
                    base_url = f"https://{api}:8443"
                else:
                    base_url = api

                # Create collector for current API
                collector = RawApiCollector(
                    base_url=base_url,
                    username=args.user,
                    password=args.password,
                    output_dir=args.output,
                    system_id=args.system_id
                )

                try:
                    # Connect to current API
                    print(f"  Connecting to {base_url}...")
                    if not collector.connect():
                        print(f"  [FAIL] Failed to connect to {api}")
                        iteration_stats['failed_apis'] += 1
                        continue

                    print(f"  [OK] Connected successfully")
                    api_success = True
                    api_endpoints = 0

                    # Collect data from current API
                    if args.category:
                        # Single category
                        category = EndpointCategory(args.category)
                        print(f"  Collecting {category.value} endpoints...")
                        results = collector.collect_by_category(category)

                        success_count = sum(1 for success in results.values() if success)
                        total_count = len(results)
                        api_endpoints = success_count

                        print(f"  Results: {success_count}/{total_count} endpoints successful")

                        if args.verbose:
                            for endpoint, success in results.items():
                                status = "[OK]" if success else "[FAIL]"
                                print(f"    {status} {endpoint}")

                    else:
                        # All categories
                        print(f"  Collecting all endpoints...")
                        all_results = collector.collect_all()

                        api_success_count = 0
                        api_total_count = 0

                        if args.verbose:
                            print(f"  Category Summary:")
                        for category, results in all_results.items():
                            success_count = sum(1 for success in results.values() if success)
                            category_count = len(results)
                            api_success_count += success_count
                            api_total_count += category_count

                            if args.verbose:
                                print(f"    {category}: {success_count}/{category_count}")

                        api_endpoints = api_success_count
                        print(f"  API Total: {api_success_count}/{api_total_count} endpoints successful")

                    if api_success:
                        iteration_stats['successful_apis'] += 1
                        iteration_stats['total_endpoints'] += api_endpoints
                        print(f"  API {api} completed successfully")

                except KeyboardInterrupt:
                    print(f"\nCollection interrupted by user during API {api}")
                    raise
                except Exception as e:
                    print(f"  Error collecting from API {api}: {e}")
                    iteration_stats['failed_apis'] += 1
                    api_success = False
                finally:
                    collector.disconnect()

            # Iteration summary
            print(f"\nIteration {iteration} Summary:")
            print(f"  Successful APIs: {iteration_stats['successful_apis']}")
            print(f"  Failed APIs: {iteration_stats['failed_apis']}")
            print(f"  Total endpoints collected: {iteration_stats['total_endpoints']}")

            # Update overall stats
            overall_stats['total_iterations'] += 1
            overall_stats['successful_apis'] += iteration_stats['successful_apis']
            overall_stats['failed_apis'] += iteration_stats['failed_apis']
            overall_stats['total_endpoints_collected'] += iteration_stats['total_endpoints']
            time_end = time.time()
            time_taken = time_end - time_begin

            # Sleep between iterations (except for the last one)
            if iteration < args.iterations:
                print(f"\n Waiting {args.interval - time_taken} seconds before next iteration...")
                time.sleep(args.interval-time_taken)

        # Final summary
        print(f"\n=== COLLECTION COMPLETE ===")
        print(f"Overall Statistics:")
        print(f"  Total iterations: {overall_stats['total_iterations']}")
        print(f"  Successful API collections: {overall_stats['successful_apis']}")
        print(f"  Failed API collections: {overall_stats['failed_apis']}")
        print(f"  Total endpoints collected: {overall_stats['total_endpoints_collected']}")
        print(f"  Files written to: {args.output}")

    except KeyboardInterrupt:
        print(f"\n Collection interrupted by user")
        print(f"Partial Statistics (before interruption):")
        print(f"  Completed iterations: {overall_stats['total_iterations']}")
        print(f"  Successful API collections: {overall_stats['successful_apis']}")
        print(f"  Failed API collections: {overall_stats['failed_apis']}")
        print(f"  Endpoints collected so far: {overall_stats['total_endpoints_collected']}")
        return 130
    except Exception as e:
        print(f"\nFatal error: {e}")
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main())

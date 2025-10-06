#!/usr/bin/env python3
"""
InfluxDB Schema Analyzer for E-Series Performance Analyzer

A comprehensive tool for analyzing, comparing, and monitoring InfluxDB schema changes.
Designed to run in the utils container with pre-configured InfluxDB access.
"""

import argparse
import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# We'll use the influxdb3 CLI tool which works with the existing certificates


class SchemaAnalyzer:
    """InfluxDB Schema Analysis Tool"""

    def __init__(self):
        """Initialize with InfluxDB connection from environment"""
        # Build connection parameters from environment variables
        self.influx_host = os.getenv('INFLUX_HOST', 'influxdb')
        self.influx_port = os.getenv('INFLUX_PORT', '8181')
        self.database = os.getenv('INFLUX_DB', 'epa')

        # Get token from file or environment
        token_file = os.getenv('INFLUXDB3_AUTH_TOKEN_FILE', '/home/influx/epa.token')
        if os.path.exists(token_file):
            with open(token_file, 'r') as f:
                self.token = f.read().strip()
        else:
            self.token = os.getenv('INFLUXDB3_AUTH_TOKEN', '')

        if not self.token:
            raise ValueError("InfluxDB token not found in file or environment")

        self.host_url = f"https://{self.influx_host}:{self.influx_port}"
        print(f"Connecting to InfluxDB: {self.host_url}")
        print(f"Database: {self.database}")
        print(f"Using influxdb3 CLI tool for queries")

    def _run_influxdb3_query(self, query: str, language: str = "sql") -> List[Dict[str, Any]]:
        """Execute query using the influxdb3 CLI tool that works with existing certs"""
        try:
            # Build the influxdb3 CLI command with explicit connection parameters
            cmd = [
                'influxdb3',
                'query',
                '--host', self.host_url,
                '--token', self.token,
                '--language', language,
                '--database', self.database,
                '--format', 'json',
                query
            ]

            # Set up environment for the CLI tool
            env = os.environ.copy()
            # Make sure the CLI uses the same certificates
            env['INFLUXDB3_TLS_CA'] = os.getenv('INFLUXDB3_TLS_CA', '/home/influx/certs/ca.crt')

            # Run the command and capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                env=env
            )

            # Parse JSON output
            if result.stdout:
                return json.loads(result.stdout)
            else:
                return []

        except subprocess.CalledProcessError as e:
            raise Exception(f"influxdb3 CLI command failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise Exception("influxdb3 CLI command timed out")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse influxdb3 CLI JSON output: {e}")

    def _get_measurements(self) -> List[str]:
        """Get list of all measurements using influxdb3 CLI"""
        try:
            print("Discovering measurements using influxdb3 CLI...")

            # Use SHOW MEASUREMENTS with InfluxQL
            result = self._run_influxdb3_query("SHOW MEASUREMENTS", "influxql")

            measurements = []
            for row in result:
                if isinstance(row, dict):
                    # Handle different possible response formats
                    if 'name' in row:
                        measurements.append(row['name'])
                    elif 'iox::measurement' in row and 'name' in row:
                        measurements.append(row['name'])
                    elif 'measurements' in row:
                        measurements.append(row['measurements'])

            return measurements

        except Exception as e:
            print(f"Could not get measurements: {e}")
            print("   Falling back to known measurement names...")

            # Fallback to known measurements from your environment
            return [
                'analyzed_controller_statistics',
                'analyzed_drive_statistics',
                'analyzed_interface_statistics',
                'analyzed_system_statistics',
                'config_controllerconfig',
                'config_driveconfig',
                'config_ethernetconfig',
                'config_hosts',
                'config_systemconfig',
                'config_trayconfig',
                'config_volumeconfig',
                'events_lockdown_status'
            ]

    def get_schema_data(self) -> Dict[str, Any]:
        """Retrieve comprehensive schema information from InfluxDB"""
        print("Retrieving schema data from InfluxDB...")

        schema_data = {
            'timestamp': datetime.now().isoformat(),
            'database': self.database,
            'measurements': {},
            'summary': {
                'total_measurements': 0,
                'total_fields': 0,
                'total_tags': 0
            }
        }

        try:
            # Get all measurements (tables)
            measurements = self._get_measurements()

            if not measurements:
                print("No measurements found")
                return schema_data

            print(f"Found {len(measurements)} measurements")
            schema_data['summary']['total_measurements'] = len(measurements)

            # For each measurement, get field and tag information
            for measurement in measurements:
                print(f"  Analyzing {measurement}...")

                measurement_data = {
                    'fields': {},
                    'tags': {},
                    'sample_count': 0
                }

                # Get schema information using DESCRIBE or similar
                try:
                    # Try to describe the table structure
                    describe_query = f"DESCRIBE {measurement}"
                    describe_result = self._run_influxdb3_query(describe_query, "sql")

                    for row in describe_result:
                        if isinstance(row, dict):
                            column_name = row.get('column_name', row.get('Field', 'unknown'))
                            column_type = row.get('data_type', row.get('Type', 'unknown'))

                            # Skip time column and system columns
                            if column_name.lower() in ['time', '_time', '_measurement']:
                                continue

                            # Assume non-time columns are fields for now
                            measurement_data['fields'][column_name] = column_type
                            schema_data['summary']['total_fields'] += 1

                except Exception as e:
                    print(f"    Warning: Could not describe {measurement}: {e}")

                    # Fallback: try to get sample data to infer schema
                    try:
                        sample_query = f"SELECT * FROM {measurement} LIMIT 1"
                        sample_result = self._run_influxdb3_query(sample_query, "sql")

                        if sample_result and isinstance(sample_result[0], dict):
                            for column_name, value in sample_result[0].items():
                                if column_name.lower() in ['time', '_time', '_measurement']:
                                    continue

                                # Infer type from value
                                if isinstance(value, bool):
                                    column_type = 'boolean'
                                elif isinstance(value, int):
                                    column_type = 'integer'
                                elif isinstance(value, float):
                                    column_type = 'float'
                                else:
                                    column_type = 'string'

                                measurement_data['fields'][column_name] = column_type
                                schema_data['summary']['total_fields'] += 1

                    except Exception as e2:
                        print(f"    Warning: Could not get sample data for {measurement}: {e2}")

                # Get approximate record count
                try:
                    count_query = f"SELECT COUNT(*) as count FROM {measurement}"
                    count_result = self._run_influxdb3_query(count_query, "sql")

                    if count_result and isinstance(count_result[0], dict):
                        count_value = count_result[0].get('count', 0)
                        measurement_data['sample_count'] = count_value

                except Exception as e:
                    print(f"    Warning: Could not get record count for {measurement}: {e}")

                schema_data['measurements'][measurement] = measurement_data
                print(f"    {measurement}: {len(measurement_data['fields'])} fields, {len(measurement_data['tags'])} tags")

        except Exception as e:
            print(f"Error retrieving schema data: {e}")
            raise

        print(f"Schema analysis complete:")
        print(f"   {schema_data['summary']['total_measurements']} measurements")
        print(f"   {schema_data['summary']['total_tags']} total tags")
        print(f"   {schema_data['summary']['total_fields']} total fields")

        return schema_data

    def dump_schema_raw(self, output_dir: str) -> str:
        """Dump schema to JSON files in timestamped directory"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dump_dir = Path(output_dir) / f"schema_dump_{timestamp}"
        dump_dir.mkdir(parents=True, exist_ok=True)

        print(f"Creating raw schema dump in: {dump_dir}")

        schema_data = self.get_schema_data()

        # Save complete schema data
        schema_file = dump_dir / "schema_complete.json"
        with open(schema_file, 'w') as f:
            json.dump(schema_data, f, indent=2, sort_keys=True)

        # Save measurements summary
        measurements_file = dump_dir / "measurements.json"
        measurements_summary = {
            'timestamp': schema_data['timestamp'],
            'measurements': list(schema_data['measurements'].keys()),
            'count': len(schema_data['measurements'])
        }
        with open(measurements_file, 'w') as f:
            json.dump(measurements_summary, f, indent=2, sort_keys=True)

        # Save fields summary
        fields_file = dump_dir / "fields.json"
        fields_summary = {
            'timestamp': schema_data['timestamp'],
            'by_measurement': {},
            'by_type': {}
        }

        for measurement, data in schema_data['measurements'].items():
            fields_summary['by_measurement'][measurement] = data['fields']

            for field_name, field_type in data['fields'].items():
                if field_type not in fields_summary['by_type']:
                    fields_summary['by_type'][field_type] = []
                fields_summary['by_type'][field_type].append(f"{measurement}.{field_name}")

        with open(fields_file, 'w') as f:
            json.dump(fields_summary, f, indent=2, sort_keys=True)

        # Save tags summary
        tags_file = dump_dir / "tags.json"
        tags_summary = {
            'timestamp': schema_data['timestamp'],
            'by_measurement': {},
            'unknown_values': {}
        }

        for measurement, data in schema_data['measurements'].items():
            tags_summary['by_measurement'][measurement] = {
                tag_name: {
                    'value_count': tag_data['value_count'],
                    'has_unknown': tag_data['has_unknown'],
                    'sample_values': tag_data['values'][:10]  # First 10 values
                }
                for tag_name, tag_data in data['tags'].items()
            }

            # Collect unknown values
            for tag_name, tag_data in data['tags'].items():
                if tag_data['has_unknown']:
                    if measurement not in tags_summary['unknown_values']:
                        tags_summary['unknown_values'][measurement] = []
                    tags_summary['unknown_values'][measurement].append(tag_name)

        with open(tags_file, 'w') as f:
            json.dump(tags_summary, f, indent=2, sort_keys=True)

        print(f"Raw schema dump saved to: {dump_dir}")
        print(f"   schema_complete.json - Full schema data")
        print(f"   measurements.json - Measurements list")
        print(f"   fields.json - Fields by measurement and type")
        print(f"   tags.json - Tags with value counts and unknowns")

        return str(dump_dir)

    def dump_schema_markdown(self, output_file: str):
        """Generate markdown schema documentation"""
        print(f"Generating markdown schema documentation: {output_file}")

        schema_data = self.get_schema_data()

        with open(output_file, 'w') as f:
            f.write("# InfluxDB Schema Documentation\n\n")
            f.write(f"Generated: {schema_data['timestamp']}\n")
            f.write(f"Database: {schema_data['database']}\n\n")

            f.write("## Summary\n\n")
            f.write(f"- **Total Measurements**: {schema_data['summary']['total_measurements']}\n")
            f.write(f"- **Total Fields**: {schema_data['summary']['total_fields']}\n")
            f.write(f"- **Total Tags**: {schema_data['summary']['total_tags']}\n\n")

            f.write("## Measurements\n\n")

            for measurement, data in sorted(schema_data['measurements'].items()):
                f.write(f"### {measurement}\n\n")
                f.write(f"**Sample Count**: ~{data['sample_count']:,}\n\n")

                if data['tags']:
                    f.write("#### Tags\n\n")
                    f.write("| Tag Name | Value Count | Sample Values | Has Unknown |\n")
                    f.write("|----------|-------------|---------------|-------------|\n")

                    for tag_name, tag_info in sorted(data['tags'].items()):
                        sample_values = ', '.join(tag_info['values'][:5])
                        if len(tag_info['values']) > 5:
                            sample_values += "..."
                        unknown_indicator = "NG" if tag_info['has_unknown'] else "OK"
                        f.write(f"| {tag_name} | {tag_info['value_count']} | {sample_values} | {unknown_indicator} |\n")
                    f.write("\n")

                if data['fields']:
                    f.write("#### Fields\n\n")
                    f.write("| Field Name | Type |\n")
                    f.write("|------------|------|\n")

                    for field_name, field_type in sorted(data['fields'].items()):
                        f.write(f"| {field_name} | {field_type} |\n")
                    f.write("\n")

        print(f"Markdown documentation saved to: {output_file}")

    def compare_schemas(self, file1: str, file2: str):
        """Compare two schema dump files"""
        print(f"Comparing schema dumps:")
        print(f"   Old: {file1}")
        print(f"   New: {file2}")

        try:
            with open(file1, 'r') as f:
                schema1 = json.load(f)
            with open(file2, 'r') as f:
                schema2 = json.load(f)
        except FileNotFoundError as e:
            print(f"Error: Schema file not found: {e}")
            return
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in schema file: {e}")
            return

        measurements1 = set(schema1['measurements'].keys())
        measurements2 = set(schema2['measurements'].keys())

        # Compare measurements
        added_measurements = measurements2 - measurements1
        removed_measurements = measurements1 - measurements2
        common_measurements = measurements1 & measurements2

        print(f"\nMeasurement Changes:")
        if added_measurements:
            print(f"   Added: {', '.join(sorted(added_measurements))}")
        if removed_measurements:
            print(f"   Removed: {', '.join(sorted(removed_measurements))}")
        if not added_measurements and not removed_measurements:
            print(f"   No measurement changes")

        # Compare fields and tags for common measurements
        field_changes = []
        tag_changes = []

        for measurement in common_measurements:
            m1_data = schema1['measurements'][measurement]
            m2_data = schema2['measurements'][measurement]

            # Field changes
            fields1 = set(m1_data['fields'].keys())
            fields2 = set(m2_data['fields'].keys())

            added_fields = fields2 - fields1
            removed_fields = fields1 - fields2

            if added_fields or removed_fields:
                field_changes.append({
                    'measurement': measurement,
                    'added': list(added_fields),
                    'removed': list(removed_fields)
                })

            # Tag changes
            tags1 = set(m1_data['tags'].keys())
            tags2 = set(m2_data['tags'].keys())

            added_tags = tags2 - tags1
            removed_tags = tags1 - tags2

            if added_tags or removed_tags:
                tag_changes.append({
                    'measurement': measurement,
                    'added': list(added_tags),
                    'removed': list(removed_tags)
                })

        print(f"\nField Changes:")
        if field_changes:
            for change in field_changes:
                print(f"   {change['measurement']}:")
                if change['added']:
                    print(f"     Added fields: {', '.join(change['added'])}")
                if change['removed']:
                    print(f"     Removed fields: {', '.join(change['removed'])}")
        else:
            print(f"   No field changes")

        print(f"\nTag Changes:")
        if tag_changes:
            for change in tag_changes:
                print(f"   {change['measurement']}:")
                if change['added']:
                    print(f"     Added tags: {', '.join(change['added'])}")
                if change['removed']:
                    print(f"     Removed tags: {', '.join(change['removed'])}")
        else:
            print(f"   No tag changes")

    def show_stats(self, schema_file: str):
        """Show statistics from a schema dump file"""
        print(f"Analyzing schema statistics: {schema_file}")

        try:
            with open(schema_file, 'r') as f:
                schema_data = json.load(f)
        except FileNotFoundError:
            print(f"Error: Schema file not found: {schema_file}")
            return
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in schema file: {e}")
            return

        print(f"\nSchema Statistics (Generated: {schema_data.get('timestamp', 'unknown')})")
        print(f"   Database: {schema_data.get('database', 'unknown')}")
        print(f"   Total Measurements: {schema_data['summary']['total_measurements']}")
        print(f"   Total Fields: {schema_data['summary']['total_fields']}")
        print(f"   Total Tags: {schema_data['summary']['total_tags']}")

        # Field type distribution
        field_types = {}
        tag_counts = {}
        measurements_with_unknowns = []

        for measurement, data in schema_data['measurements'].items():
            # Count field types
            for field_name, field_type in data['fields'].items():
                field_types[field_type] = field_types.get(field_type, 0) + 1

            # Count tags per measurement
            tag_count = len(data['tags'])
            if tag_count not in tag_counts:
                tag_counts[tag_count] = 0
            tag_counts[tag_count] += 1

            # Check for unknown values
            has_unknowns = any(tag_data.get('has_unknown', False) for tag_data in data['tags'].values())
            if has_unknowns:
                measurements_with_unknowns.append(measurement)

        print(f"\nField Type Distribution:")
        for field_type, count in sorted(field_types.items()):
            print(f"   {field_type}: {count} fields")

        print(f"\nTag Count Distribution:")
        for tag_count, measurement_count in sorted(tag_counts.items()):
            print(f"   {tag_count} tags: {measurement_count} measurements")

        if measurements_with_unknowns:
            print(f"\nMeasurements with 'unknown' tag values:")
            for measurement in sorted(measurements_with_unknowns):
                print(f"   {measurement}")
        else:
            print(f"No measurements have 'unknown' tag values")

    def find_missing(self, schema_dir: str, keys: List[str]):
        """Find measurements with missing/unknown values for specified keys"""
        print(f"Searching for missing values in: {schema_dir}")
        print(f"Target keys: {', '.join(keys)}")

        schema_dir_path = Path(schema_dir)

        # Find the most recent schema dump
        schema_files = list(schema_dir_path.glob("*/schema_complete.json"))
        if not schema_files:
            print(f"Error: No schema dumps found in {schema_dir}")
            return

        # Use the most recent dump
        latest_schema = max(schema_files, key=lambda x: x.stat().st_mtime)
        print(f"Using schema dump: {latest_schema}")

        try:
            with open(latest_schema, 'r') as f:
                schema_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error reading schema file: {e}")
            return

        print(f"Analyzing {len(schema_data['measurements'])} measurements...")

        issues_found = {}

        for measurement, data in schema_data['measurements'].items():
            measurement_issues = []

            for key in keys:
                if key in data['tags']:
                    tag_data = data['tags'][key]
                    if tag_data.get('has_unknown', False):
                        unknown_count = tag_data['values'].count('unknown')
                        total_count = tag_data['value_count']
                        measurement_issues.append({
                            'key': key,
                            'issue': f"Has 'unknown' values ({unknown_count}/{total_count})",
                            'sample_values': tag_data['values'][:5]
                        })
                else:
                    measurement_issues.append({
                        'key': key,
                        'issue': "Key not found in tags",
                        'sample_values': []
                    })

            if measurement_issues:
                issues_found[measurement] = measurement_issues

        if issues_found:
            print(f"Found issues in {len(issues_found)} measurements:")

            for measurement, issues in sorted(issues_found.items()):
                print(f"\n   {measurement}:")
                for issue in issues:
                    print(f"      {issue['key']}: {issue['issue']}")
                    if issue['sample_values']:
                        sample_str = ', '.join(issue['sample_values'][:3])
                        print(f"         Sample values: {sample_str}")
        else:
            print(f"No issues found for the specified keys")

    def handle_error(self, e: Exception):
        print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='InfluxDB Schema Analyzer for E-Series Performance Analyzer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dump schema to markdown documentation
  python3 schema_analyzer.py dump-schema --dest markdown --output /docs/SCHEMA.md

  # Dump schema to raw JSON files
  python3 schema_analyzer.py dump-schema --dest raw --output /data/samples/out/

  # Compare two schema dumps
  python3 schema_analyzer.py compare schema_dump_20231201_120000/schema_complete.json schema_dump_20231201_130000/schema_complete.json

  # Show statistics from a schema dump
  python3 schema_analyzer.py stats schema_dump_20231201_120000/schema_complete.json

  # Find measurements with unknown system identification
  python3 schema_analyzer.py findmissing /data/samples/out/ --keys system_wwn,system_id,storage_system_name
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Dump schema command
    dump_parser = subparsers.add_parser('dump-schema', help='Dump InfluxDB schema')
    dump_parser.add_argument('--dest', choices=['markdown', 'raw'], required=True,
                            help='Output destination format')
    dump_parser.add_argument('--output', required=True,
                            help='Output file (markdown) or directory (raw)')

    # Compare schemas command
    compare_parser = subparsers.add_parser('compare', help='Compare two schema dumps')
    compare_parser.add_argument('file1', help='First schema dump file')
    compare_parser.add_argument('file2', help='Second schema dump file')

    # Show stats command
    stats_parser = subparsers.add_parser('stats', help='Show schema statistics')
    stats_parser.add_argument('schema_file', help='Schema dump file to analyze')

    # Find missing command
    missing_parser = subparsers.add_parser('findmissing', help='Find missing/unknown values')
    missing_parser.add_argument('schema_dir', help='Directory containing schema dumps')
    missing_parser.add_argument('--keys', required=True,
                               help='Comma-separated list of keys to check (e.g. system_wwn,system_id)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        analyzer = SchemaAnalyzer()

        if args.command == 'dump-schema':
            if args.dest == 'markdown':
                analyzer.dump_schema_markdown(args.output)
            elif args.dest == 'raw':
                analyzer.dump_schema_raw(args.output)

        elif args.command == 'compare':
            analyzer.compare_schemas(args.file1, args.file2)

        elif args.command == 'stats':
            analyzer.show_stats(args.schema_file)

        elif args.command == 'findmissing':
            keys = [k.strip() for k in args.keys.split(',')]
            analyzer.find_missing(args.schema_dir, keys)

        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
#!/bin/sh

# Docker/Kubernetes Entrypoint for E-Series Performance Analyzer Collector (New DataSource Architecture)
#
# (c) 2025 scaleoutSean (Github)
# License: MIT
#
# This entrypoint is designed for containerized deployments using environment variables.
# Configuration is provided via ENV vars in docker-compose.yaml or Kubernetes manifests.
# 
# For CLI usage with config files, run the collector directly:
# python3 -m collector --json-directory ./data --system-id-filter XXXX
# Or: python3 -m collector --management-ip 192.168.1.100 --username monitor --password secret
#
# System name (sysname) and system ID (sysid/WWN) are auto-detected by Collector 
# from the API. No need to provide them manually as it was done in EPA v3.
#
# Required environment variables for containerized mode:
# - INFLUX_HOST: InfluxDB server hostname (e.g., influxdb)
# - INFLUX_PORT: InfluxDB server port (e.g., 8181)  
# - INFLUX_DB: InfluxDB database/bucket name (e.g., epa)
# - INFLUXDB3_AUTH_TOKEN_FILE: Path to InfluxDB authentication token file
# - API: Comma-separated list of E-Series API endpoints (e.g., 10.0.0.1,10.0.0.2)  
# - USERNAME: E-Series management username (e.g., monitor)
# - PASSWORD: E-Series management password
#
# Optional environment variables:
# - TLS_CA: Path to CA certificate file for API/InfluxDB TLS verification
# - INFLUXDB3_TLS_CA: Path to CA certificate file for TLS verification
# - TLS_VALIDATION: TLS validation mode (strict, normal, none) - default: strict
# - INTERVAL_TIME: Collection interval in seconds - default: 300
# - COLLECTOR_LOG_LEVEL: Log level (DEBUG, INFO, WARNING, ERROR) - default: INFO
# - MAX_ITERATIONS: Maximum iterations before exit - default: 0 (infinite)
# - SYSTEM_ID: Filter JSON replay to specific system ID (WWN) - only used with FROM_JSON
# - FROM_JSON: Directory to replay previously collected JSON metrics
# - OUTPUT: Output format (influxdb, prometheus, both) - default: influxdb (secure)
# - PROMETHEUS_PORT: Prometheus metrics port - default: 8000

# Check for --config argument and reject it in containerized mode
for arg in "$@"; do
    case $arg in
        --config)
            echo "ERROR: --config is not supported in containerized mode"
            echo "Use environment variables in docker-compose.yaml or Kubernetes manifests"
            echo "For CLI usage with config files, run the collector directly outside containers"
            exit 1
            ;;
    esac
done

# Build command line arguments from environment variables
ARGS=""

# Build InfluxDB URL from INFLUX_HOST and INFLUX_PORT
if [ -n "$INFLUX_HOST" ] && [ -n "$INFLUX_PORT" ]; then
    INFLUX_URL="https://$INFLUX_HOST:$INFLUX_PORT"
    ARGS="$ARGS --influxdbUrl $INFLUX_URL"
fi

# InfluxDB database (if specified, otherwise defaults to 'epa')
if [ -n "$INFLUX_DB" ]; then
    ARGS="$ARGS --influxdbDatabase $INFLUX_DB"
fi

# Read InfluxDB token from file if specified
if [ -n "$INFLUXDB3_AUTH_TOKEN_FILE" ] && [ -f "$INFLUXDB3_AUTH_TOKEN_FILE" ]; then
    TOKEN=$(cat "$INFLUXDB3_AUTH_TOKEN_FILE" | tr -d '\n\r')
    if [ -n "$TOKEN" ]; then
        ARGS="$ARGS --influxdbToken $TOKEN"
    fi
fi

# JSON replay mode takes precedence over API mode (old collector format)
if [ -n "$FROM_JSON" ]; then
    ARGS="$ARGS --fromJson $FROM_JSON"
    if [ -n "$SYSTEM_ID" ]; then
        ARGS="$ARGS --systemId $SYSTEM_ID"
    fi
    echo "INFO: JSON replay mode enabled - skipping API configuration"
# E-Series API endpoints and credentials (only if FROM_JSON not set)
elif [ -n "$API" ] && [ -n "$USERNAME" ] && [ -n "$PASSWORD" ]; then
    # Convert comma-separated API list to space-separated for --api argument
    API_LIST=$(echo "$API" | tr ',' ' ')
    ARGS="$ARGS --api $API_LIST"
    ARGS="$ARGS --username $USERNAME --password $PASSWORD"
    echo "INFO: Live API mode enabled"
fi

# Output format
if [ -n "$OUTPUT" ]; then
    ARGS="$ARGS --output $OUTPUT"
else
    # Default to both InfluxDB and Prometheus
    ARGS="$ARGS --output both"
fi

# Prometheus port
if [ -n "$PROMETHEUS_PORT" ]; then
    ARGS="$ARGS --prometheus-port $PROMETHEUS_PORT"
fi

# Optional arguments
if [ -n "$TLS_CA" ]; then
    ARGS="$ARGS --tlsCa $TLS_CA"
fi

if [ -n "$TLS_VALIDATION" ]; then
    ARGS="$ARGS --tlsValidation $TLS_VALIDATION"
fi

if [ -n "$INTERVAL_TIME" ]; then
    ARGS="$ARGS --intervalTime $INTERVAL_TIME"
fi

# Use COLLECTOR_LOG_LEVEL with backward compatibility fallback to LOG_LEVEL
LOG_LEVEL_VALUE="${COLLECTOR_LOG_LEVEL:-${LOG_LEVEL}}"
if [ -n "$LOG_LEVEL_VALUE" ]; then
    ARGS="$ARGS --log-level $LOG_LEVEL_VALUE"
fi

if [ -n "$MAX_ITERATIONS" ]; then
    ARGS="$ARGS --maxIterations $MAX_ITERATIONS"
fi

if [ -n "$COLLECTOR_LOG_FILE" ] && [ "$COLLECTOR_LOG_FILE" != "None" ]; then
    ARGS="$ARGS --logfile $COLLECTOR_LOG_FILE"
fi

# Environment monitoring collection options
if [ -n "$INCLUDE_ENVIRONMENTAL" ] && [ "$INCLUDE_ENVIRONMENTAL" = "false" ]; then
    ARGS="$ARGS --no-environmental"
fi

if [ -n "$INCLUDE_EVENTS" ] && [ "$INCLUDE_EVENTS" = "false" ]; then
    ARGS="$ARGS --no-events"  
fi

# Change to the collector directory and run the new collector
cd /home/collector

# Debug output (only if COLLECTOR_LOG_LEVEL is DEBUG)
if [ "$COLLECTOR_LOG_LEVEL" = "DEBUG" ] || [ "$LOG_LEVEL" = "DEBUG" ]; then
    echo "DEBUG: Executing: python -m collector $ARGS $*"
fi

exec python -m collector $ARGS "$@"

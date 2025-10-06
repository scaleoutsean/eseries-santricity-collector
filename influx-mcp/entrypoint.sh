#!/bin/sh
set -e

# read INFLUXDB3_AUTH_TOKEN_FILE env var if set and load token from file
if [ -n "$INFLUXDB3_AUTH_TOKEN_FILE" ] && [ -f "$INFLUXDB3_AUTH_TOKEN_FILE" ]; then
        export INFLUX_DB_TOKEN=$(cat "$INFLUXDB3_AUTH_TOKEN_FILE")
fi

# now exec your server
exec node build/index.js

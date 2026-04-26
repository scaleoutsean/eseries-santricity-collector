#!/bin/bash
set -e

# Default directories
TOKEN_ROOT="/home/influx/tokens"
mkdir -p "${TOKEN_ROOT}"

echo "Starting InfluxDB initialization script..."

# 1. Admin Token
# We check for admin.token file. 
if [ ! -f "${TOKEN_ROOT}/admin.token" ]; then
    echo "Creating admin token (offline)..."
    # Create token JSON
    # Note: --host is likely ignored in --offline but required by strict argument parsing if present? 
    # We include it just in case, mirroring old usage, but --offline handles the work.
    influxdb3 create token --admin --offline --name "admin-token" --host "https://influxdb:8181" --output-file "${TOKEN_ROOT}/admin.json"
    
    # Extract token string
    if [ -f "${TOKEN_ROOT}/admin.json" ]; then
        # Simple extraction for {"token": "..."}
        grep -o '"token": *"[^"]*"' "${TOKEN_ROOT}/admin.json" | cut -d'"' -f4 > "${TOKEN_ROOT}/admin.token"
        echo "Admin token created."
    else
        echo "Error: Failed to create admin token json."
    fi
else
    echo "Admin token already exists."
fi

# 2. EPA Token
if [ ! -f "${TOKEN_ROOT}/epa.token" ]; then
    echo "Creating EPA token (offline)..."
    influxdb3 create token --admin --offline --name "epa" --host "https://influxdb:8181" --output-file "${TOKEN_ROOT}/epa.json"
    
    if [ -f "${TOKEN_ROOT}/epa.json" ]; then
        grep -o '"token": *"[^"]*"' "${TOKEN_ROOT}/epa.json" | cut -d'"' -f4 > "${TOKEN_ROOT}/epa.token"
        echo "EPA token created."
    else
        echo "Error: Failed to create EPA token json."
    fi
else
    echo "EPA token already exists."
fi

# Ensure permissions (best effort)
chmod 644 "${TOKEN_ROOT}"/*.token 2>/dev/null || true

echo "Detailed initialization complete. Starting Server..."

exec influxdb3 serve \
  --node-id="${NODE_ID:-1}" \
  --object-store="file" \
  --data-dir="/var/lib/influxdb3" \
  --tls-key="${TLS_KEY}" \
  --tls-cert="${TLS_CERT}" \
  --tls-minimum-version="${TLS_MIN_VERSION:-tls-1.3}" \
  --http-bind="0.0.0.0:8181" \
  --wal-flush-interval="${WAL_FLUSH_INTERVAL:-10s}" \
  --admin-token-recovery-http-bind="0.0.0.0:8182"

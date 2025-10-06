#!/usr/bin/env bash
set -euo pipefail

# Simple helper to check upstream TLS verification from within the proxy container
# Usage: ./scripts/check_upstream_tls.sh

PROXY_CONTAINER_NAME="proxy"

INFLUX_HOST=${INFLUX_HOST:-influxdb}
INFLUX_PORT=${INFLUX_PORT:-8181}
GRAFANA_HOST=${GRAFANA_HOST:-grafana}
GRAFANA_PORT=${GRAFANA_PORT:-3443}

echo "Checking upstream TLS from inside container '$PROXY_CONTAINER_NAME'..."

check() {
    local host=$1
    local port=$2
    local sni=$3

    echo -n "Checking $host:$port (SNI=$sni) ... "
    if docker compose exec -T "$PROXY_CONTAINER_NAME" \
         openssl s_client -connect "$host:$port" -servername "$sni" -CAfile /etc/nginx/ssl/combined_ca.crt </dev/null 2>/tmp/openssl.out; then
        # capture verify code
        tail -n 1 /tmp/openssl.out | sed -n 's/^.*Verify return code: \([0-9]*\).*$/\1/p' > /tmp/verify.code || true
        code=$(cat /tmp/verify.code 2>/dev/null || echo "")
        if [[ "$code" == "0" ]]; then
            echo "OK"
            return 0
        else
            echo "FAIL (verify code: ${code:-unknown})"
            echo "--- openssl output (truncated) ---"
            tail -n 40 /tmp/openssl.out || true
            return 1
        fi
    else
        echo "ERROR running openssl inside container"
        docker compose exec -T "$PROXY_CONTAINER_NAME" cat /tmp/openssl.out || true
        return 2
    fi
}

echo
check "$INFLUX_HOST" "$INFLUX_PORT" "$INFLUX_HOST" || true
echo
check "$GRAFANA_HOST" "$GRAFANA_PORT" "$GRAFANA_HOST" || true

echo
echo "Done. If checks fail, inspect /nginx-logs/error.log in the proxy container and ensure combined CA contains both internal and external CA certs."

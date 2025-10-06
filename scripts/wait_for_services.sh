#!/usr/bin/env bash
# Wait for services to become healthy or their HTTP endpoints to respond.
# Usage: ./scripts/wait_for_services.sh explorer influxdb grafana
# If no services are provided, waits for explorer,influxdb,grafana by default.

set -euo pipefail

SERVICES=(${@:-explorer influxdb grafana})
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# max wait seconds per service
MAX_WAIT=${MAX_WAIT:-180}
SLEEP=3

echo "Waiting for services: ${SERVICES[*]}"

for svc in "${SERVICES[@]}"; do
  echo "\nStarting and waiting for $svc"
  # start the service (safe to start even if already running)
  docker compose up -d "$svc" || true

  # check docker compose health status if available
  i=0
  while true; do
    # Prefer checking docker compose health status
    status=$(docker compose ps --format "{{.Name}} {{.State}} {{.Health}}" | grep -E "\b${svc}\b" || true)
    if echo "$status" | grep -q "healthy"; then
      echo "$svc is healthy"
      break
    fi

    # If no health info available, try a simple service-specific probe
    case "$svc" in
      explorer)
        # explorer serves HTTPS by default; use hostname 'explorer' inside the network
        if docker compose exec -T explorer bash -c "curl -k -fsS https://localhost:${EXPLORER_PORT} >/dev/null 2>&1"; then
          echo "explorer responded OK"
          break
        fi
        ;;
      influxdb)
        if docker compose exec -T influxdb bash -c "curl -k -fsS https://localhost:8181/health >/dev/null 2>&1"; then
          echo "influxdb responded OK"
          break
        fi
        ;;
      grafana)
        if docker compose exec -T grafana bash -c "curl -k -fsS http://localhost:3000/ >/dev/null 2>&1"; then
          echo "grafana responded OK"
          break
        fi
        ;;
      *)
        # generic: check container is running
        if docker compose ps "$svc" | grep -q Up; then
          echo "$svc container is up (no healthcheck)."
          break
        fi
        ;;
    esac

    i=$((i+SLEEP))
    if [ "$i" -ge "$MAX_WAIT" ]; then
      echo "Timed out waiting for $svc after ${MAX_WAIT}s"
      exit 1
    fi
    sleep $SLEEP
  done
done

echo "\nAll requested services are up/healthy"

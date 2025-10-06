#!/usr/bin/bash
# Ensure correct ownership of data directories for current user

# if we're in scripts/, go up one directory
if [ "$(basename "$PWD")" == "scripts" ]; then
    cd ..
fi

# if we're not in the root directory and ./data directory does not exist, exit with error
if [ ! -f "docker-compose.yml" ] && [ ! -d "data" ]; then
    echo "Error: Please run this script from the root directory of the project"
    exit 1
fi

# if ./data/influxdb_tokens or ./data/influxdb_credentials exist, change ownership to current user
# If this script is invoked via 'sudo', use the original user's UID/GID so
# ownership is set to the non-root user. If not, fall back to the current
# user's id.
TARGET_UID=${SUDO_UID:-$(id -u)}
TARGET_GID=${SUDO_GID:-$(id -g)}

# Use a unique temporary error file to avoid permission collisions when the script
# was previously run as root or another user. Create via mktemp and ensure it's
# removed on exit.
TMPERR=$(mktemp /tmp/fix_chown.XXXXXX) || TMPERR="/tmp/fix_chown.err"
trap 'rm -f "$TMPERR"' EXIT

for dir in data/influxdb_tokens data/influxdb_credentials; do
    if [ -d "$dir" ]; then
        echo "Ensuring ownership of $dir is ${TARGET_UID}:${TARGET_GID}"
        # use safe_chown helper so errors like "no new privileges" are detected
        if ! sudo chown -R "${TARGET_UID}:${TARGET_GID}" "$dir" 2>"$TMPERR"; then
            err=$(cat "$TMPERR" || true)
                        echo "Error: failed to chown $dir"
                        if echo "$err" | grep -qi "no new privileges"; then
                                cat <<'MSG'
It looks like 'sudo' cannot escalate privileges in this environment ("no new privileges").
This commonly happens when running inside a container or when the kernel prohibits privilege escalation.

Suggested remediation:
    1) Stop the related containers so they don't hold mounts on the host directories:
         docker compose down grafana influxdb
    2) Remove or fix the offending directories on the host (BE CAREFUL, this deletes data):
         rm -rf ./data/grafana ./data/influxdb
    3) Recreate directories and re-run this script as your normal user:
         ./scripts/fix_data_dir_ownership.sh

If you prefer to try chown manually as root instead, run:
    sudo chown -R ${TARGET_UID}:${TARGET_GID} "$dir"

MSG
                        else
                                echo "$err"
                        fi
                        exit 1
                fi
    else
        echo "Directory $dir does not exist, creating it and setting ownership to ${TARGET_UID}:${TARGET_GID}"
        mkdir -p "$dir"
        if ! sudo chown -R "${TARGET_UID}:${TARGET_GID}" "$dir" 2>"$TMPERR"; then
            err=$(cat "$TMPERR" || true)
            echo "Error: failed to chown $dir"
            echo "$err"
            exit 1
        fi
    fi
done

# Grafana

GRAF_DIR="./data/grafana/storage"
GRAF_CERT_DIR="./certs/grafana"

if [ -d "$GRAF_DIR" ]; then
    echo "Ensuring ownership of $GRAF_DIR is 472:472"
else
    echo "$GRAF_DIR does not exist; creating it"
    mkdir -p "$GRAF_DIR"
fi
if ! sudo chown -R 472:472 "$GRAF_DIR"; then
    echo "Error: failed to chown $GRAF_DIR"
    exit 1
fi

if [ -d "$GRAF_CERT_DIR" ]; then
    echo "Ensuring ownership of $GRAF_CERT_DIR is 472:472"
    if ! sudo chown -R 472:472 "$GRAF_CERT_DIR"; then
        echo "Warning: failed to chown $GRAF_CERT_DIR"
    fi
else
    echo "Warning: $GRAF_CERT_DIR does not exist; skipping"
fi

echo
echo "Note: if Grafana is currently running as a container, the ownership change may not affect the running container's filesystem mounts." \
    "To ensure the change takes effect, stop/remove the Grafana container and restart it after this script finishes:" \
    "\n  docker compose down grafana\n  # run this script (no need to run the whole script under sudo; it will prompt as needed)\n  docker compose up -d grafana\n"

echo
echo "Recommendation: Run this script as your normal user. The script will use 'sudo' where necessary and will set ownership to your original user even if you accidentally invoked it with sudo. Avoid running the entire script as root to prevent chowning files to root (0:0)."


# Check all private keys have restrictive permissions
find ./certs/ -name "*.key" -o -name "*private*" -type f -exec ls -la {} \;
# Should all show: -rw------- (600 permissions)


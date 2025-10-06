#!/usr/bin/env bash
set -euo pipefail

# Download external repository data and merge into local 'influx-mcp' folder
# By default do not overwrite local files (e.g. custom entrypoint.sh). Use --force
# to overwrite.

REPO_URL="https://github.com/influxdata/influxdb3_mcp_server"
TARGET_DIR="influx-mcp"
TMP_DIR=""
FORCE=0

for arg in "$@"; do
	case "$arg" in
		--force) FORCE=1 ;;
		*) ;;
	esac
done

echo "Fetching ${REPO_URL} into temporary directory..."
TMP_DIR=$(mktemp -d)
git clone --depth 1 "$REPO_URL" "$TMP_DIR"

if [[ ! -d "$TMP_DIR" ]]; then
	echo "Failed to clone into $TMP_DIR" >&2
	exit 1
fi

mkdir -p "$TARGET_DIR"

echo "Merging files into ./$TARGET_DIR (force=${FORCE})"

# rsync options: copy recursively, preserve perms, verbose; exclude .git
# default behavior: don't overwrite existing files unless --force
RSYNC_OPTS=( -av --exclude='.git' )
if [[ $FORCE -eq 0 ]]; then
	RSYNC_OPTS+=( --ignore-existing )
fi

# Explicitly avoid overwriting local entrypoint.sh unless forced
RSYNC_OPTS+=( --exclude='entrypoint.sh' )

rsync "${RSYNC_OPTS[@]}" "$TMP_DIR/" "$TARGET_DIR/"

if [[ $FORCE -eq 1 ]]; then
	echo "Copying entrypoint.sh (force)"
	cp -f "$TMP_DIR/entrypoint.sh" "$TARGET_DIR/entrypoint.sh" || true
else
	if [[ ! -f "$TARGET_DIR/entrypoint.sh" && -f "$TMP_DIR/entrypoint.sh" ]]; then
		echo "Copying upstream entrypoint.sh (no local one present)"
		cp "$TMP_DIR/entrypoint.sh" "$TARGET_DIR/entrypoint.sh"
	else
		echo "Leaving local entrypoint.sh intact (use --force to overwrite)"
	fi
fi

echo "Cleanup temporary directory"
rm -rf "$TMP_DIR"

echo "Done. Files merged into $TARGET_DIR"


#!/bin/sh
set -eu

BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
SCRIPT_DIR="${SCRIPT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"

while true; do
  sh "${SCRIPT_DIR}/backup_database.sh" || true
  sleep "$BACKUP_INTERVAL_SECONDS"
done

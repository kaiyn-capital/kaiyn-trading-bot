#!/bin/sh
set -eu

BACKUP_INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"

while true; do
  sh /scripts/backup_database.sh || true
  sleep "$BACKUP_INTERVAL_SECONDS"
done

#!/bin/sh
set -eu

COMPOSE="${COMPOSE:-docker compose}"
HOST_BACKUP_DIR="${BACKUP_DIR:-backups}"

mkdir -p "$HOST_BACKUP_DIR"

echo "Downloading latest encrypted backup from Cloudflare R2."
$COMPOSE run --rm db-backup python /scripts/r2_backup.py download-latest \
  --output-dir /backups \
  --status-output /backups/r2_restore_status.json \
  --filename-output /backups/r2_latest_backup_filename.txt

downloaded_filename="$(cat "$HOST_BACKUP_DIR/r2_latest_backup_filename.txt")"
if [ -z "$downloaded_filename" ]; then
  echo "R2 download did not write a backup filename." >&2
  exit 1
fi

BACKUP_FILE="${HOST_BACKUP_DIR}/${downloaded_filename}" COMPOSE="$COMPOSE" sh scripts/restore_latest_backup.sh

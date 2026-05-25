#!/bin/sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-kaiyn_trading_bot}"
POSTGRES_USER="${POSTGRES_USER:-kaiyn}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-kaiyn}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
BACKUP_LOCAL_KEEP_COUNT="${BACKUP_LOCAL_KEEP_COUNT:-3}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
completed_at=""
backup_name="kaiyn_trading_bot_${timestamp}.sql"
backup_path="${BACKUP_DIR}/${backup_name}"
backup_gz_path="${backup_path}.gz"
checksum_path="${backup_gz_path}.sha256"
status_path="${BACKUP_DIR}/backup_status.json"
manifest_path="${BACKUP_DIR}/backup_manifest.json"

echo "$(date) Starting PostgreSQL backup: ${backup_name}.gz"

cleanup_failed_artifacts() {
  rm -f "$backup_path" "$backup_gz_path" "$checksum_path"
}

write_failed_status() {
  failed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"failed","timestamp":"%s","filename":"%s.gz","error":"pg_dump failed"}\n' \
    "$failed_at" "$backup_name" > "$status_path"
}

prune_old_backups() {
  find "$BACKUP_DIR" -type f -name "kaiyn_trading_bot_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
  find "$BACKUP_DIR" -type f -name "kaiyn_trading_bot_*.sql.gz.sha256" -mtime +"$RETENTION_DAYS" -delete

  if [ "$BACKUP_LOCAL_KEEP_COUNT" -gt 0 ]; then
    count=0
    find "$BACKUP_DIR" -type f -name "kaiyn_trading_bot_*.sql.gz" | sort -r | while IFS= read -r file; do
      count=$((count + 1))
      if [ "$count" -gt "$BACKUP_LOCAL_KEEP_COUNT" ]; then
        rm -f "$file" "${file}.sha256"
      fi
    done
  fi
}

if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
  --host "$POSTGRES_HOST" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --no-owner \
  --no-privileges \
  --file "$backup_path" &&
  gzip -f "$backup_path"; then
  checksum="$(sha256sum "$backup_gz_path" | awk '{print $1}')"
  size_bytes="$(wc -c < "$backup_gz_path" | tr -d ' ')"
  printf '%s  %s\n' "$checksum" "$(basename "$backup_gz_path")" > "$checksum_path"
  completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"success","timestamp":"%s","filename":"%s.gz"}\n' \
    "$completed_at" "$backup_name" > "$status_path"
  printf '{"status":"success","timestamp":"%s","filename":"%s.gz","sha256":"%s","size_bytes":%s,"database":"%s"}\n' \
    "$completed_at" "$backup_name" "$checksum" "$size_bytes" "$POSTGRES_DB" > "$manifest_path"
  prune_old_backups
  echo "$(date) PostgreSQL backup completed: ${backup_name}.gz"
else
  cleanup_failed_artifacts
  write_failed_status
  echo "$(date) PostgreSQL backup failed"
  exit 1
fi

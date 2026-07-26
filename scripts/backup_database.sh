#!/bin/sh
set -eu
umask 077

SCRIPT_DIR="${SCRIPT_DIR:-$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-kaiyn_trading_bot}"
POSTGRES_USER="${POSTGRES_USER:-kaiyn}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
BACKUP_LOCAL_KEEP_COUNT="${BACKUP_LOCAL_KEEP_COUNT:-3}"
R2_BACKUP_ENABLED="${R2_BACKUP_ENABLED:-false}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
completed_at=""
backup_name="kaiyn_trading_bot_${timestamp}.sql"
backup_path="${BACKUP_DIR}/${backup_name}"
backup_gz_path="${backup_path}.gz"
checksum_path="${backup_gz_path}.sha256"
status_path="${BACKUP_DIR}/backup_status.json"
manifest_path="${BACKUP_DIR}/backup_manifest.json"
r2_status_path="${BACKUP_DIR}/r2_backup_status.json"

echo "$(date) Starting PostgreSQL backup: ${backup_name}.gz"

cleanup_failed_artifacts() {
  rm -f "$backup_path" "$backup_gz_path" "$checksum_path"
}

write_failed_status() {
  error_message="${1:-pg_dump failed}"
  failed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"failed","timestamp":"%s","filename":"%s.gz","error":"%s"}\n' \
    "$failed_at" "$backup_name" "$error_message" > "$status_path"
}

write_r2_failed_status() {
  failed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"failed","timestamp":"%s","filename":"%s.gz","error":"r2 upload failed"}\n' \
    "$failed_at" "$backup_name" > "$r2_status_path"
}

upload_r2_backup() {
  case "$(printf '%s' "$R2_BACKUP_ENABLED" | tr '[:upper:]' '[:lower:]')" in
    true | 1 | yes | on) ;;
    *) return 0 ;;
  esac

  echo "$(date) Uploading encrypted PostgreSQL backup to Cloudflare R2: ${backup_name}.gz"
  if python "${SCRIPT_DIR}/r2_backup.py" upload \
    --file "$backup_gz_path" \
    --manifest "$manifest_path" \
    --status-output "$r2_status_path"; then
    echo "$(date) Cloudflare R2 backup upload completed: ${backup_name}.gz"
    return 0
  fi

  write_r2_failed_status
  write_failed_status "r2 upload failed"
  echo "$(date) Cloudflare R2 backup upload failed"
  return 1
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
  upload_r2_backup
  prune_old_backups
  echo "$(date) PostgreSQL backup completed: ${backup_name}.gz"
else
  cleanup_failed_artifacts
  write_failed_status "pg_dump failed"
  echo "$(date) PostgreSQL backup failed"
  exit 1
fi

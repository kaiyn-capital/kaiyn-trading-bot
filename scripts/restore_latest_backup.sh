#!/bin/sh
set -eu

COMPOSE="${COMPOSE:-docker compose}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_FILE="${BACKUP_FILE:-}"
CONFIRM_RESTORE="${CONFIRM_RESTORE:-}"
RUN_MIGRATIONS_AFTER_RESTORE="${RUN_MIGRATIONS_AFTER_RESTORE:-true}"

find_latest_backup() {
  find "$BACKUP_DIR" -type f -name "kaiyn_trading_bot_*.sql.gz" | sort -r | head -n 1
}

calc_sha256() {
  file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  else
    echo "sha256sum or shasum is required to verify backup checksums" >&2
    exit 1
  fi
}

if [ -z "$BACKUP_FILE" ]; then
  if [ ! -d "$BACKUP_DIR" ]; then
    echo "Backup directory does not exist: $BACKUP_DIR" >&2
    exit 1
  fi
  BACKUP_FILE="$(find_latest_backup)"
fi

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
  echo "No backup file found. Run make backup-now first, or set BACKUP_FILE=path/to/backup.sql.gz." >&2
  exit 1
fi

checksum_file="${BACKUP_FILE}.sha256"
if [ -f "$checksum_file" ]; then
  expected_checksum="$(awk '{print $1}' "$checksum_file")"
  actual_checksum="$(calc_sha256 "$BACKUP_FILE")"
  if [ "$expected_checksum" != "$actual_checksum" ]; then
    echo "Backup checksum mismatch: $BACKUP_FILE" >&2
    exit 1
  fi
  echo "Checksum verified: $BACKUP_FILE"
else
  echo "No checksum file found for $BACKUP_FILE; continuing without checksum verification." >&2
fi

$COMPOSE up -d postgres

POSTGRES_DB="${POSTGRES_DB:-$($COMPOSE exec -T postgres sh -c 'printf "%s" "$POSTGRES_DB"')}"
POSTGRES_USER="${POSTGRES_USER:-$($COMPOSE exec -T postgres sh -c 'printf "%s" "$POSTGRES_USER"')}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$($COMPOSE exec -T postgres sh -c 'printf "%s" "$POSTGRES_PASSWORD"')}"

table_count="$($COMPOSE exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres psql \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  -Atc "select count(*) from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE';")"

if [ "$table_count" -gt 0 ] && [ "$CONFIRM_RESTORE" != "YES" ]; then
  echo "Target database is not empty (${table_count} tables)." >&2
  echo "Refusing to restore without explicit confirmation." >&2
  echo "Run again with CONFIRM_RESTORE=YES if you intend to replace the current database." >&2
  exit 1
fi

if [ "$CONFIRM_RESTORE" = "YES" ]; then
  echo "Dropping existing public schema before restore."
  $COMPOSE exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres psql \
    -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -c "drop schema if exists public cascade; create schema public;"
fi

echo "Restoring backup: $BACKUP_FILE"
gunzip -c "$BACKUP_FILE" | $COMPOSE exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres psql \
  -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB"

if [ "$RUN_MIGRATIONS_AFTER_RESTORE" = "true" ]; then
  $COMPOSE run --rm bot alembic upgrade head
  $COMPOSE run --rm bot python -m app.main --check-db
fi

echo "Restore completed: $BACKUP_FILE"

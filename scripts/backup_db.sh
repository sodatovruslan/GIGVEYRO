#!/usr/bin/env bash
# ==============================================================
# GIGVEYRO — PostgreSQL Backup Script
#
# Usage:
#   ./scripts/backup_db.sh [backup_dir]
#
# Examples:
#   ./scripts/backup_db.sh
#   ./scripts/backup_db.sh /mnt/backups
#
# Environment variables:
#   POSTGRES_HOST     (default: localhost)
#   POSTGRES_PORT     (default: 5432)
#   POSTGRES_DB       (default: gigveyro)
#   POSTGRES_USER     (default: gigveyro_user)
#   PGPASSWORD        — set this to avoid interactive password prompt
#                       (or use ~/.pgpass file)
#
# Output:
#   {backup_dir}/gigveyro_{YYYYMMDD_HHMMSS}.dump
#
# Retention:
#   Set BACKUP_RETAIN_DAYS to auto-delete older backups (default: 30)
#
# SECURITY:
#   - NEVER hardcode credentials in this script
#   - Use PGPASSWORD env var or ~/.pgpass
#   - Store backups in encrypted, access-controlled storage
#   - Verify backups with restore_db.sh periodically
# ==============================================================

set -euo pipefail

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-gigveyro}"
POSTGRES_USER="${POSTGRES_USER:-gigveyro_user}"
BACKUP_RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-30}"
BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/gigveyro_${TIMESTAMP}.dump"

echo "[backup] Starting PostgreSQL backup of '${POSTGRES_DB}' @ ${POSTGRES_HOST}:${POSTGRES_PORT}"
echo "[backup] Output: ${BACKUP_FILE}"

mkdir -p "${BACKUP_DIR}"

# pg_dump with custom format (-Fc) for compressed, parallel-restore-capable backup
pg_dump \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT}" \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --format=custom \
    --compress=9 \
    --no-password \
    --file="${BACKUP_FILE}"

echo "[backup] Backup complete: ${BACKUP_FILE} ($(du -sh "${BACKUP_FILE}" | cut -f1))"

# Remove backups older than BACKUP_RETAIN_DAYS
if [ "${BACKUP_RETAIN_DAYS}" -gt 0 ]; then
    echo "[backup] Removing backups older than ${BACKUP_RETAIN_DAYS} days..."
    find "${BACKUP_DIR}" -name "gigveyro_*.dump" -mtime "+${BACKUP_RETAIN_DAYS}" -delete
    echo "[backup] Cleanup done."
fi

echo "[backup] Done. Verify backup integrity with scripts/restore_db.sh"

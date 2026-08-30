#!/usr/bin/env bash
# ==============================================================
# GIGVEYRO — PostgreSQL Restore Script
#
# Usage:
#   ./scripts/restore_db.sh <backup_file> [target_db]
#
# Examples:
#   ./scripts/restore_db.sh backups/gigveyro_20260101_120000.dump
#   ./scripts/restore_db.sh backups/gigveyro_20260101_120000.dump gigveyro_restore_test
#
# Environment variables:
#   POSTGRES_HOST     (default: localhost)
#   POSTGRES_PORT     (default: 5432)
#   POSTGRES_USER     (default: gigveyro_user)
#   PGPASSWORD        — set this to avoid interactive password prompt
#
# IMPORTANT SAFETY RULES:
#   - Always restore to a SEPARATE test database first
#   - Verify data integrity before switching production
#   - NEVER restore directly over production without backup + approval
#   - Run alembic upgrade head after restore if schema changed
# ==============================================================

set -euo pipefail

BACKUP_FILE="${1:-}"
TARGET_DB="${2:-gigveyro_restore_test}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-gigveyro_user}"
RESTORE_CONFIRM_TARGET="${RESTORE_CONFIRM_TARGET:-}"

if [ -z "${BACKUP_FILE}" ]; then
    echo "ERROR: No backup file specified."
    echo "Usage: $0 <backup_file> [target_db]"
    exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

if [[ ! "${TARGET_DB}" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "ERROR: Target database name may contain only letters, numbers, and underscores."
    exit 1
fi

if [[ ! "${POSTGRES_USER}" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "ERROR: PostgreSQL user name may contain only letters, numbers, and underscores."
    exit 1
fi

if [ "${RESTORE_CONFIRM_TARGET}" != "${TARGET_DB}" ]; then
    echo "ERROR: Restore confirmation is missing or does not match the target."
    echo "Set RESTORE_CONFIRM_TARGET=${TARGET_DB} after verifying the target is disposable."
    exit 1
fi

echo "[restore] Restoring from: ${BACKUP_FILE}"
echo "[restore] Target database: ${TARGET_DB} @ ${POSTGRES_HOST}:${POSTGRES_PORT}"
echo ""
echo "WARNING: This will DROP and recreate the target database '${TARGET_DB}'."
echo "Explicit target confirmation accepted."

# Drop and recreate target database (safe for test restores)
psql \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT}" \
    --username="${POSTGRES_USER}" \
    --dbname="postgres" \
    --command="DROP DATABASE IF EXISTS \"${TARGET_DB}\";"

psql \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT}" \
    --username="${POSTGRES_USER}" \
    --dbname="postgres" \
    --command="CREATE DATABASE \"${TARGET_DB}\" OWNER \"${POSTGRES_USER}\";"

echo "[restore] Database created. Restoring data..."

pg_restore \
    --host="${POSTGRES_HOST}" \
    --port="${POSTGRES_PORT}" \
    --username="${POSTGRES_USER}" \
    --dbname="${TARGET_DB}" \
    --no-password \
    --verbose \
    "${BACKUP_FILE}"

echo ""
echo "[restore] Restore complete to '${TARGET_DB}'."
echo "[restore] Verify data, then run: alembic upgrade head (if needed)"

#!/bin/bash
# ──────────────────────────────────────────────────────────────────
# Daily PostgreSQL backup script for Original
#
# Usage:   ./backup.sh
# Cron:    0 3 * * * /opt/original/deploy/backup.sh >> /var/log/original-backup.log 2>&1
#
# Backs up to local directory and optionally syncs to S3.
# Keeps the last 14 daily backups locally.
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────
# When COMPOSE_DIR is set (e.g. COMPOSE_DIR=/opt/original), the script runs
# `docker compose exec -T postgres pg_dump ...` from that directory — no need to
# guess the postgres container name. Otherwise falls back to docker exec + DB_CONTAINER.
COMPOSE_DIR="${COMPOSE_DIR:-}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-/opt/original/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
DB_CONTAINER="${DB_CONTAINER:-original-postgres-1}"

# S3 (optional — leave S3_BUCKET empty to skip)
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-original/db-backups}"

# ── Create backup ─────────────────────────────────────────────────
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="original_db_${TIMESTAMP}.sql.gz"
BACKUP_PATH="${BACKUP_DIR}/${FILENAME}"

mkdir -p "${BACKUP_DIR}"

echo "[$(date -Iseconds)] Starting backup → ${BACKUP_PATH}"

if [ -n "${COMPOSE_DIR}" ] && [ -d "${COMPOSE_DIR}" ] && [ -f "${COMPOSE_DIR}/${COMPOSE_FILE}" ]; then
  echo "[$(date -Iseconds)] Using: docker compose -f ${COMPOSE_DIR}/${COMPOSE_FILE} exec -T postgres"
  (cd "${COMPOSE_DIR}" && docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U original -Fc original_db) | gzip > "${BACKUP_PATH}"
else
  echo "[$(date -Iseconds)] Using: docker exec ${DB_CONTAINER}"
  docker exec "${DB_CONTAINER}" \
    pg_dump -U original -Fc original_db \
    | gzip > "${BACKUP_PATH}"
fi

FILESIZE=$(du -h "${BACKUP_PATH}" | cut -f1)
echo "[$(date -Iseconds)] Backup complete: ${FILESIZE}"

# ── Upload to S3 (optional) ──────────────────────────────────────
if [ -n "${S3_BUCKET}" ]; then
    echo "[$(date -Iseconds)] Uploading to s3://${S3_BUCKET}/${S3_PREFIX}/${FILENAME}"
    aws s3 cp "${BACKUP_PATH}" "s3://${S3_BUCKET}/${S3_PREFIX}/${FILENAME}" --quiet
    echo "[$(date -Iseconds)] S3 upload complete"
fi

# ── Prune old backups ─────────────────────────────────────────────
echo "[$(date -Iseconds)] Pruning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "original_db_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete

REMAINING=$(ls -1 "${BACKUP_DIR}"/original_db_*.sql.gz 2>/dev/null | wc -l)
echo "[$(date -Iseconds)] Done. ${REMAINING} backup(s) retained."

#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/opt/carfst/backups"
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/pg_${DATE}.sql.gz"

PGPASSWORD="${DATABASE_PASSWORD:?}" pg_dump -h "${DATABASE_HOST:-localhost}" -U "${DATABASE_USER:-carfst}" "${DATABASE_NAME:-carfst}" | gzip > "$FILE"

echo "Backup created at $FILE"
echo "Добавьте в cron: 0 3 * * * /opt/carfst/deployment/backup_pg.sh >> /var/log/pg_backup.log 2>&1"







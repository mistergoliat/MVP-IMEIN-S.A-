#!/usr/bin/env bash
set -euo pipefail

TS=$(date +%F_%H%M)
mkdir -p backups
docker exec ops-db-1 pg_dump -U ${POSTGRES_USER:-appuser} ${POSTGRES_DB:-pickingdb} > backups/pickingdb_${TS}.sql
# keep last 7 days
find backups -type f -name 'pickingdb_*.sql' -mtime +7 -delete

echo "Backup created: backups/pickingdb_${TS}.sql"


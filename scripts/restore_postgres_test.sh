#!/usr/bin/env bash
set -euo pipefail
: "${DAYBREAK_RESTORE_DSN:?DAYBREAK_RESTORE_DSN is required}"
BACKUP=${1:?usage: restore_postgres_test.sh BACKUP}
pg_restore --clean --if-exists --no-owner --no-acl --dbname="$DAYBREAK_RESTORE_DSN" "$BACKUP"
psql "$DAYBREAK_RESTORE_DSN" -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version;'

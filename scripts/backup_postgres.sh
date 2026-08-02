#!/usr/bin/env bash
set -euo pipefail
: "${DAYBREAK_DATABASE_DSN:?DAYBREAK_DATABASE_DSN is required}"
DESTINATION=${1:?usage: backup_postgres.sh DESTINATION}
mkdir -p "$(dirname "$DESTINATION")"
umask 077
pg_dump --format=custom --no-owner --no-acl --dbname="$DAYBREAK_DATABASE_DSN" --file="$DESTINATION"
test -s "$DESTINATION"
sha256sum "$DESTINATION"

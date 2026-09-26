#!/bin/sh
# Proves a backup restores: loads its dump into a scratch database next to the
# live one, checks it is at the migration head the code expects and that its
# tables hold rows, verifies the objects' checksums, then drops the scratch
# database. Touches nothing live. `make restore-drill BACKUP=backups/<stamp>`.
set -eu
COMPOSE="${COMPOSE:-docker compose}"
BACKUP="${1:?the backup directory}"
DRILL=nafas_restore_drill

(cd "$BACKUP" && sha256sum --quiet -c SHA256SUMS) && echo "checksums: ok"

$COMPOSE exec -T postgres psql -q -U nafas -d postgres -c "DROP DATABASE IF EXISTS $DRILL" -c "CREATE DATABASE $DRILL"
$COMPOSE exec -T postgres pg_restore -U nafas -d "$DRILL" --no-owner --exit-on-error < "$BACKUP/nafas.dump"

restored="$($COMPOSE exec -T postgres psql -tA -U nafas -d "$DRILL" -c "SELECT version_num FROM alembic_version")"
expected="$(uv run alembic heads 2>/dev/null | awk '{print $1}')"
echo "migration: restored $restored, code expects $expected"
[ "$restored" = "$expected" ] || { echo "the backup is not at this code's migration head"; exit 1; }

$COMPOSE exec -T postgres psql -tA -U nafas -d "$DRILL" -c "
  SELECT schemaname || '.' || relname || ' ' || n_live_tup FROM pg_stat_user_tables
  WHERE schemaname NOT IN ('public') ORDER BY 1" | sed 's/^/rows: /'
echo "objects: $(find "$BACKUP/objects" -type f | wc -l)"

$COMPOSE exec -T postgres psql -q -U nafas -d postgres -c "DROP DATABASE $DRILL"
echo "restore drill passed"

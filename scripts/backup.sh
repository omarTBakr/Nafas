#!/bin/sh
# One backup: the database (pg_dump, custom format) and every stored object,
# into BACKUP_DIR/<UTC timestamp>, with checksums. `make backup`.
#
# Backups hold patient data. With AGE_RECIPIENT set (and `age` installed) the
# whole backup is encrypted to that key and the plain copy removed; set it
# everywhere but a laptop, and keep the private key off the backup host.
# Prove a backup restores with `make restore-drill BACKUP=...`.
set -eu
COMPOSE="${COMPOSE:-docker compose}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR:-backups}/$STAMP"
mkdir -p "$OUT"

$COMPOSE exec -T postgres pg_dump -U nafas -d nafas --format=custom > "$OUT/nafas.dump"
uv run python -m scripts.backup_storage save "$OUT/objects"
git rev-parse --short HEAD > "$OUT/commit" 2>/dev/null || true
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

if [ -n "${AGE_RECIPIENT:-}" ]; then
  tar -C "$(dirname "$OUT")" -cf - "$STAMP" | age -r "$AGE_RECIPIENT" > "$OUT.tar.age"
  rm -rf "$OUT"
  echo "backup encrypted: $OUT.tar.age"
else
  echo "backup (not encrypted; set AGE_RECIPIENT outside a laptop): $OUT"
fi

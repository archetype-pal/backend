#!/usr/bin/env bash
#
# Offline TEI migration of a production backup.
#
# Loads an input PostgreSQL dump into a scratch database, brings its schema to
# the current codebase, converts ImageText.content from data-dpt HTML to TEI
# P5 XML (reversible), re-encodes the TEXT-graph reverse links, gates on
# integrity + well-formedness, then dumps the migrated database back out.
#
# No production system is touched: everything runs in a throwaway scratch DB
# inside the local postgres container. The returned dump is verified before it
# is written.
#
# Usage:
#   scripts/migrate_backup_to_tei.sh INPUT_DUMP.sql OUTPUT_DUMP.sql [SCRATCH_DB]
#
# Run from the api/ directory with the compose stack's postgres up.
# Note: the search index (Meilisearch) is NOT part of the DB dump — after the
# returned backup is restored, run `just sync-all-search-indexes` there.

set -euo pipefail

INPUT="${1:?usage: migrate_backup_to_tei.sh INPUT_DUMP OUTPUT_DUMP [SCRATCH_DB]}"
OUTPUT="${2:?output dump path required}"
SCRATCH="${3:-tei_migration_scratch}"

if [[ ! -f "$INPUT" ]]; then
  echo "Input dump not found: $INPUT" >&2
  exit 1
fi

# Derive the scratch DATABASE_URL from the configured one (swap the db name),
# so credentials/host are never hard-coded here.
BASE_URL="$(grep -E '^DATABASE_URL=' config/.env | head -1 | cut -d= -f2- | tr -d '"')"
if [[ -z "$BASE_URL" ]]; then
  echo "DATABASE_URL not found in config/.env" >&2
  exit 1
fi
SCRATCH_URL="$(printf '%s' "$BASE_URL" | sed -E "s#/[^/?]+(\\?|$)#/${SCRATCH}\\1#")"

psql_scratch() { docker compose exec -T postgres psql -U postgres -d "$SCRATCH" "$@"; }
manage() { docker compose run --rm --no-deps -e DATABASE_URL="$SCRATCH_URL" -T api python manage.py "$@"; }

echo "==> (re)creating scratch database '$SCRATCH'"
docker compose exec -T postgres psql -U postgres -d postgres \
  -c "DROP DATABASE IF EXISTS ${SCRATCH};" -c "CREATE DATABASE ${SCRATCH};"

echo "==> loading input dump: $INPUT"
# ON_ERROR_STOP=1 so a truncated/corrupt dump aborts the load (set -e then
# fails the whole run) rather than silently producing a partial DB that the
# downstream gates would happily pass off as a 'verified' backup.
docker compose exec -T postgres psql -U postgres -d "$SCRATCH" -q -v ON_ERROR_STOP=1 < "$INPUT" >/dev/null

echo "==> sanity: ImageText rows loaded"
ROWS="$(psql_scratch -tA -c 'SELECT count(*) FROM manuscripts_imagetext')"
if [[ -z "$ROWS" || "$ROWS" -eq 0 ]]; then
  echo "Refusing to migrate: no manuscripts_imagetext rows loaded (got '${ROWS}')." >&2
  exit 1
fi
echo "    loaded ${ROWS} image-text rows"

echo "==> applying schema migrations"
manage migrate --noinput

echo "==> converting content data-dpt -> TEI (round-trip-verified)"
manage migrate_imagetext_to_tei --apply

echo "==> re-encoding TEXT-graph reverse links"
manage reencode_graph_elementid --apply

echo "==> integrity gate: text<->region links"
manage check_text_links

echo "==> validity gate: every ImageText.content is well-formed TEI XML"
manage verify_tei

echo "==> dumping migrated database -> $OUTPUT"
docker compose exec -T postgres pg_dump -U postgres --no-owner --no-privileges "$SCRATCH" > "$OUTPUT"

echo "==> dropping scratch database"
docker compose exec -T postgres psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH};"

echo "==> done. Migrated, verified backup written to: $OUTPUT"
echo "    Reminder: after restoring it, run 'just sync-all-search-indexes' to rebuild search."

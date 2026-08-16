#!/usr/bin/env bash
#
# Offline TEI migration of a production backup.
#
# Loads an input PostgreSQL dump into a scratch database, brings its schema to
# the current codebase, converts ImageText.content from data-dpt HTML to TEI
# P5 XML, re-encodes the TEXT-graph reverse links, gates on integrity +
# well-formedness, then dumps the migrated database back out.
#
# NOT reversible: since ROADMAP H.11 the schema step also drops
# manuscripts_imagetext.content_dpt_legacy, so a dump taken after the May TEI
# migration loses its retained data-dpt here. That step is therefore gated on
# `verify_tei_cutover` (see "cutover gate" below), which aborts the run unless
# dropping the column provably loses nothing.
#
# No production system is touched: everything runs in a throwaway scratch DB
# inside the local postgres container. The returned dump is verified before it
# is written.
#
# Usage:
#   scripts/migrate_backup_to_tei.sh INPUT_DUMP.sql OUTPUT_DUMP.sql [SCRATCH_DB]
#
# Run from any directory with the compose stack's postgres up.
# Note: the search index (Meilisearch) is NOT part of the DB dump — after the
# returned backup is restored, run `just sync-all-search-indexes` there.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

INPUT="${1:?usage: migrate_backup_to_tei.sh INPUT_DUMP OUTPUT_DUMP [SCRATCH_DB]}"
OUTPUT="${2:?output dump path required}"
SCRATCH="${3:-tei_migration_scratch}"

if [[ ! -f "$INPUT" ]]; then
  echo "Input dump not found: $INPUT" >&2
  exit 1
fi

# Absolutise the dump paths against the caller's cwd before moving to the repo root.
OUTPUT_DIR="$(cd "$(dirname "$OUTPUT")" 2>/dev/null && pwd)" || {
  echo "Output directory not found: $(dirname "$OUTPUT")" >&2
  exit 1
}
INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"
OUTPUT="${OUTPUT_DIR}/$(basename "$OUTPUT")"

cd "$ROOT_DIR"

# Derive the scratch DATABASE_URL from the configured one (swap the db name),
# so credentials/host are never hard-coded here.
ENV_FILE="${API_ENV_FILE:-config/.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: ${ENV_FILE} (create it: cp config/test.env config/.env)" >&2
  exit 1
fi
BASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' || true)"
if [[ -z "$BASE_URL" ]]; then
  echo "DATABASE_URL not found in ${ENV_FILE}" >&2
  exit 1
fi
SCRATCH_URL="$(printf '%s' "$BASE_URL" | sed -E "s#/[^/?]+(\\?|$)#/${SCRATCH}\\1#")"

# Compose only auto-loads a project-root .env; this project keeps its env under
# config/, and omitting it makes compose interpolate every ${VAR} to blank.
compose() { docker compose --env-file "$ENV_FILE" "$@"; }
psql_scratch() { compose exec -T postgres psql -U postgres -d "$SCRATCH" "$@"; }
manage() { compose run --rm --no-deps -e DATABASE_URL="$SCRATCH_URL" -T api python manage.py "$@"; }
drop_scratch() { compose exec -T postgres psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH};"; }

# The load runs before any gate, so an abort must not strand a populated scratch DB.
trap 'drop_scratch >/dev/null 2>&1 || true' EXIT

echo "==> (re)creating scratch database '$SCRATCH'"
compose exec -T postgres psql -U postgres -d postgres \
  -c "DROP DATABASE IF EXISTS ${SCRATCH};" -c "CREATE DATABASE ${SCRATCH};"

echo "==> loading input dump: $INPUT"
# ON_ERROR_STOP=1 so a truncated/corrupt dump aborts the load (set -e then
# fails the whole run) rather than silently producing a partial DB that the
# downstream gates would happily pass off as a 'verified' backup.
compose exec -T postgres psql -U postgres -d "$SCRATCH" -q -v ON_ERROR_STOP=1 < "$INPUT" >/dev/null

echo "==> sanity: ImageText rows loaded"
ROWS="$(psql_scratch -tA -c 'SELECT count(*) FROM manuscripts_imagetext')"
if [[ -z "$ROWS" || "$ROWS" -eq 0 ]]; then
  echo "Refusing to migrate: no manuscripts_imagetext rows loaded (got '${ROWS}')." >&2
  exit 1
fi
echo "    loaded ${ROWS} image-text rows"

echo "==> cutover gate: may the schema step drop content_dpt_legacy?"
# The `migrate` below includes 0024, which drops the retention column. On a dump
# taken after the May TEI migration that column is populated, so this pipeline
# would otherwise perform the irreversible H.11 cutover with no evidence and
# hand the result back as a "verified" backup. Gate it. Skipped when the column
# is absent or empty (e.g. a pre-TEI dump), where the drop destroys nothing and
# the gate's no-data-dpt-residue check would legitimately fail anyway.
HAS_LEGACY="$(psql_scratch -tA -c "SELECT count(*) FROM information_schema.columns \
  WHERE table_name = 'manuscripts_imagetext' AND column_name = 'content_dpt_legacy'")"
RETAINED=0
if [[ "${HAS_LEGACY:-0}" -gt 0 ]]; then
  RETAINED="$(psql_scratch -tA -c "SELECT count(*) FROM manuscripts_imagetext \
    WHERE content_dpt_legacy IS NOT NULL AND content_dpt_legacy <> ''")"
fi
if [[ "${RETAINED:-0}" -gt 0 ]]; then
  echo "    ${RETAINED} row(s) carry retained data-dpt that the schema step will destroy — gating."
  # Extra gate arguments (e.g. --migrated-at / --accept-superseded) come from
  # the operator; set -e aborts the run on a non-zero verdict.
  # shellcheck disable=SC2086
  manage verify_tei_cutover --min-rows "$ROWS" ${TEI_CUTOVER_GATE_ARGS:-}
else
  echo "    skipped: no retained data-dpt in this dump — the drop destroys nothing."
fi

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
compose exec -T postgres pg_dump -U postgres --no-owner --no-privileges "$SCRATCH" > "$OUTPUT"

echo "==> dropping scratch database"
drop_scratch
trap - EXIT

echo "==> done. Migrated, verified backup written to: $OUTPUT"
echo "    Reminder: after restoring it, run 'just sync-all-search-indexes' to rebuild search."

# TEI backup migration runbook

> **The full runbook now lives in the superproject: `docs/tei.md` §5.** That
> document is canonical for everything TEI — both workstreams, every phase item,
> the open H.11 retention cutover, and the gate semantics. This file is the
> terminal-side summary, kept here so a backend-only clone still has the
> commands.

Migrate a production PostgreSQL backup from `data-dpt` HTML storage to TEI P5
XML, offline, and return a verified migrated backup. **No production system is
touched** — everything runs in a throwaway scratch database. We are handed a
backup, migrate it, and return a new one; we do *not* run the migration against
the live database.

## The one command

From `api/`, with the compose stack's `postgres` container up:

```bash
scripts/migrate_backup_to_tei.sh  prod_backup.sql  migrated_backup.sql
```

Idempotent and safe to re-run. It loads the dump into a scratch DB, runs the
H.11 cutover gate if `content_dpt_legacy` is still populated, migrates the
schema, converts `ImageText.content` to TEI (only rows that round-trip
byte-for-byte), re-encodes the graph element ids, then gates on
`check_text_links` (integrity) and `verify_tei` (validity) before dumping the
result. **If either gate fails it stops before writing the output**, so a bad
migration never produces a returned backup.

Pass extra cutover-gate arguments via `TEI_CUTOVER_GATE_ARGS`, e.g.
`TEI_CUTOVER_GATE_ARGS='--migrated-at 2026-05-31 --accept-superseded'`.

## The read-only checks

```bash
python manage.py verify_tei                        # all content is well-formed TEI
python manage.py check_text_links                  # no dangling text→region links
python manage.py verify_tei_cutover --min-rows 899 # safe to drop content_dpt_legacy?
```

`verify_tei_cutover` exit codes: **0** safe to drop · **1** a check failed ·
**2** the column is already absent (deliberately non-zero — "already applied" is
not "verified safe to apply").

## After the migrated backup is restored

The search index is **not** part of a DB dump. Rebuild it once:

```bash
just sync-all-search-indexes
```

## Reversibility

**There is no TEI rollback.** `migrate_imagetext_to_tei` is forward-only; the
only way back to `data-dpt` is `tei_to_data_dpt`, which regenerates it from the
TEI on demand. (`reencode_graph_elementid --reverse` still exists — that one
keeps its legacy tuple in `legacy_dpt_elementid`.)

See `docs/tei.md` §4.1 in the superproject for the 5 non-reproducible rows that
currently block the retention drop, and §5 for the full procedure.

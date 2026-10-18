# TEI backup migration runbook

> The full procedure, its reasoning and the manual step-by-step version live in
> the superproject: **`docs/tei.md` §5.3**. This file is the terminal-side
> summary, so a backend-only clone still has the commands.

Migrate a PostgreSQL backup whose `ImageText.content` is still `data-dpt` HTML
to TEI P5 XML, offline, and return a verified migrated backup. Everything runs
in a throwaway scratch database: we are handed a backup, migrate it, and return
a new one. **The live database is never migrated in place.**

## The one command

From `api/`, with the compose stack's `postgres` container up:

```bash
SEARCH_AUTO_REINDEX=false scripts/migrate_backup_to_tei.sh prod_backup.sql migrated_backup.sql [SCRATCH_DB]
```

- The input must be a **plain-SQL dump** (it is loaded with `psql`). Convert a
  custom-format dump first: `pg_restore -f prod_backup.sql dump`.
- `SEARCH_AUTO_REINDEX=false` stops every rewritten row queuing search syncs,
  which are pointless here because the index is rebuilt after restore.
- Idempotent and safe to re-run.

It loads the dump, runs the cutover gate if `content_dpt_legacy` is still
populated, runs `migrate` (which drops that column and, through migration
`0027`, embeds text↔region links that exist only on the graphs into the text),
converts the content to TEI (only rows that round-trip byte-for-byte),
re-encodes the graph element ids, then gates on `check_text_links` (integrity)
and `verify_tei` (validity) before dumping the result. **If either gate fails
it stops before writing the output.**

Pass extra cutover-gate arguments via `TEI_CUTOVER_GATE_ARGS`, e.g.
`TEI_CUTOVER_GATE_ARGS='--migrated-at 2026-05-31 --accept-superseded'`.

## The read-only checks

```bash
python manage.py verify_tei                        # all content is well-formed TEI
python manage.py check_text_links                  # no dangling text→region links
python manage.py verify_tei_cutover --min-rows 899 # safe to drop content_dpt_legacy?
```

`verify_tei_cutover` exit codes: **0** safe to drop · **1** a check failed ·
**2** the column is already absent (deliberately non-zero: "already applied" is
not "verified safe to apply").

## After the migrated backup is restored

The search index is **not** part of a database dump. Rebuild it once:

```bash
just sync-all-search-indexes
```

## Reversibility

**There is no TEI rollback.** `content_dpt_legacy` was dropped (migration
`0025_drop_content_dpt_legacy`, in production since 2026-08-29), so
`migrate_imagetext_to_tei` is forward-only. The only way back to `data-dpt` is
`tei_to_data_dpt`, which regenerates it from the TEI on demand.
`reencode_graph_elementid --reverse` still exists; it keeps its legacy tuple in
`legacy_dpt_elementid`.

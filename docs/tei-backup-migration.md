# TEI backup migration runbook

How to migrate a production PostgreSQL backup from `data-dpt` HTML storage to
TEI P5 XML, offline, and return a verified migrated backup. No production
system is touched — everything runs in a throwaway scratch database.

## When to use

The agreed production workflow: we are handed a DB backup, apply the TEI
migration to it, and return a new backup with the migrated data. (We do **not**
run the migration against the live database.)

## One command

From `api/`, with the compose stack's `postgres` container up:

```bash
scripts/migrate_backup_to_tei.sh  prod_backup.sql  migrated_backup.sql
```

That script (idempotent, safe to re-run) does, in order:

1. Create a throwaway scratch database and load `prod_backup.sql` into it.
2. `migrate` — bring the schema to the current codebase (adds
   `manuscripts_imagetext.content_dpt_legacy`, the reversible retention column).
2b. *(only for older backups whose text has no embedded links yet)*
   `embed_annotation_ids --from-graphs --apply` — if `ImageText.content`
   (data-dpt) carries no `data-graph-id` but the graphs still hold the legacy
   `properties.elementid` tuples, this embeds the text↔region links into the
   data-dpt **before** the TEI step (the `data-graph-id` then becomes `corresp`
   in step 3). Skip for backups already exported with linked data-dpt.
3. `migrate_imagetext_to_tei --apply` — convert `ImageText.content` from
   data-dpt HTML to TEI XML. Each row's original is kept in
   `content_dpt_legacy`; conversion is only applied to rows that round-trip
   byte-for-byte (canonical-form), and non-round-tripping rows are reported.
4. `reencode_graph_elementid --apply` — re-encode each TEXT graph's
   `properties.elementid` to its reverse element link (legacy tuple preserved
   under `legacy_dpt_elementid`).
5. `check_text_links` — **integrity gate**: aborts if any text→region link
   points at a missing, non-TEXT, or cross-image Graph.
6. `verify_tei` — **validity gate**: aborts unless every `ImageText.content`
   is well-formed TEI XML (also catches any row that did not convert).
7. `pg_dump` the scratch DB to `migrated_backup.sql`, then drop the scratch DB.

If either gate fails the script stops **before** writing the output, so a bad
migration never produces a returned backup.

## After the migrated backup is restored

The search index is **not** part of a DB dump. On the system where the migrated
backup is restored, rebuild Meilisearch once:

```bash
just sync-all-search-indexes
```

## Reversibility

`content_dpt_legacy` retains the original data-dpt for every migrated row, so a
restored database can be rolled back with
`python manage.py migrate_imagetext_to_tei --reverse` (and
`reencode_graph_elementid --reverse`). Drop the legacy column only after a
retention window via the standard migration (ROADMAP Phase H.11).

## Validation

The script was validated end-to-end against a faithful pre-migration dump
(data-dpt content, no `content_dpt_legacy` column): 899/899 rows converted,
5,901 text↔region links resolved with 0 integrity problems, 0 invalid-XML rows.

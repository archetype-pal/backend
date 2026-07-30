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
1b. **Cutover gate** — if the loaded dump still has a populated
   `content_dpt_legacy`, run `verify_tei_cutover --min-rows <loaded rows>` and
   abort on a non-zero verdict, because the next step destroys that column.
   Skipped when the column is absent or empty (a pre-TEI dump), where the drop
   destroys nothing. Pass extra gate arguments via the `TEI_CUTOVER_GATE_ARGS`
   environment variable, e.g.
   `TEI_CUTOVER_GATE_ARGS='--migrated-at 2026-05-31 --accept-superseded'`.
2. `migrate` — bring the schema to the current codebase. Since the H.11 cutover
   this also **drops** `manuscripts_imagetext.content_dpt_legacy`: on a dump
   taken after the May TEI migration, the retained data-dpt goes with it. This
   is irreversible, which is why step 1b gates it.
2b. *(only for older backups whose text has no embedded links yet)*
   `embed_annotation_ids --from-graphs --apply` — if `ImageText.content`
   (data-dpt) carries no `data-graph-id` but the graphs still hold the legacy
   `properties.elementid` tuples, this embeds the text↔region links into the
   data-dpt **before** the TEI step (the `data-graph-id` then becomes `corresp`
   in step 3). Skip for backups already exported with linked data-dpt.
3. `migrate_imagetext_to_tei --apply` — convert `ImageText.content` from
   data-dpt HTML to TEI XML. Conversion is only applied to rows that round-trip
   byte-for-byte (canonical-form), and non-round-tripping rows are reported and
   left as data-dpt. Rows that are already TEI are skipped, so the step is a
   no-op on a re-run.
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

**There is no TEI rollback any more.** ROADMAP Phase H.11 dropped
`content_dpt_legacy` (migration `0024_remove_imagetext_content_dpt_legacy`), so
`migrate_imagetext_to_tei` is forward-only and `--reverse` is gone. TEI is the
canonical storage format; the only way back to data-dpt is `tei_to_data_dpt`,
which regenerates it from the TEI on demand. (`reencode_graph_elementid
--reverse` still exists — that one keeps its own legacy tuple in
`legacy_dpt_elementid`.)

Before applying that drop to any database that still has the column — production
or a post-May dump loaded into the scratch DB — run the gate:

```bash
python manage.py verify_tei_cutover --min-rows 899
```

It is read-only. Exit codes: `0` safe to drop, `1` a check failed, `2` the
column is already absent so nothing was gated (deliberately non-zero — "already
applied" is not "verified safe to apply").

It fails unless the corpus has at least `--min-rows` rows (state the size you
expect, so a wrong `DATABASE_URL` cannot certify the cutover against an empty or
unrelated database), every `ImageText.content` is well-formed TEI, no row still
holds data-dpt, no row's retained HTML is its only copy, and every retained
value regenerates from the TEI.

`--migrated-at <ISO>` is optional and **weakens** the gate: a row whose content
was rewritten after that timestamp has retained HTML that is stale by design, so
it is reported under `legacy-superseded` rather than as a regeneration failure.
Those rows still block the run — their pre-edit HTML genuinely cannot be
regenerated and the drop destroys it — until you review every listed id and
re-run with `--accept-superseded`. Set `--migrated-at` to the **end** of the
migration window, never earlier: too early an ISO date sweeps real losses into
the superseded bucket. A status change alone (Draft→Review→Live) bumps
`modified` without touching `content`, so rows whose latest write is a
`StatusTransition` are not exempted. If nothing at all is left to verify the gate
fails rather than passing vacuously.

The `tei_migration_failures` check (checklist item 4) reports `SKIP` when the
table is absent: nothing in this codebase ever wrote that table, so its absence
is not evidence. `no-data-dpt-residue` is the real signal — a row that failed
the migration was left as data-dpt.

Checklist items it cannot decide (search re-index completion, the H.4 search
regression suite, `data-dpt` support tickets, KNOWLEDGEBASE.md design principle
\#1) are printed as an explicit hand-off.

## Validation

The script was validated end-to-end against a faithful pre-migration dump
(data-dpt content, no `content_dpt_legacy` column): 899/899 rows converted,
5,901 text↔region links resolved with 0 integrity problems, 0 invalid-XML rows.

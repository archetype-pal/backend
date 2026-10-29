# Migrating a DigiPal database to Archetype (text storage: data-dpt → TEI)

This guide is for an institution that runs a DigiPal-era database and is
adopting Archetype. It is self-contained: everything you need is in this
repository.

## What changes, and why

DigiPal stored transcriptions and translations (`manuscripts_imagetext.content`)
as HTML with `data-dpt` attributes:

```html
<p><span data-dpt="clause" data-dpt-type="address">Omnibus hominibus</span> …</p>
```

Archetype stores the same texts as TEI P5 fragments:

```xml
<p><seg type="address" corresp="#gid-42">Omnibus hominibus</seg> …</p>
```

Two things move during the migration:

1. **The markup.** `data-dpt` spans become TEI elements (`clause`→`seg`,
   `person`→`persName`, `place`→`placeName`, `ex`, `supplied`, `lb`). The
   mapping is `apps/manuscripts/services/tei/mapping.py`; the conversion is
   checked per row by converting back and comparing, and a row is only
   rewritten if it survives that round-trip **and** parses as XML.
2. **The text↔region links.** DigiPal linked a region on the image (a `Graph`
   row of type `text`) to its transcription element on the *graph* side only,
   as `annotation.properties.elementid` (e.g. `[["", "clause"], ["type",
   "address"]]`). Archetype records the link in the text, as
   `corresp="#gid-<graph id>"`, and records the reverse link on the graph for
   the IIIF/W3C publishers. The migration writes both.

Everything runs offline against a **copy** of your database. Your live
database is never touched; you get a new, verified dump back.

## Prerequisites

- A clone of this repository with the Docker Compose dev stack and
  `config/.env` (see the README: `cp config/test.env config/.env`).
- The compose `postgres` service running (`just up-bg`).
- A **plain-SQL** PostgreSQL dump of the DigiPal database. Convert a
  custom-format dump first: `pg_restore -f dump.sql dump.custom`.
- Optional but recommended: `SEARCH_AUTO_REINDEX=false` in the environment of
  the run. Every rewritten row would otherwise queue a search sync, which is
  wasted work because the search index is rebuilt after the restore anyway.

## The one command

From the repository root:

```bash
SEARCH_AUTO_REINDEX=false scripts/migrate_backup_to_tei.sh input.sql migrated.sql
```

The script loads `input.sql` into a scratch database (`tei_migration_scratch`
by default; a third argument names another), runs the stages below, and
writes `migrated.sql` **only if every gate passes**. It is idempotent: re-run
it after fixing data and it will do the same work again from the input dump.
The scratch database is dropped on exit, success or failure.

Restore `migrated.sql` into your Archetype database, then rebuild the search
index (it is not part of a dump):

```bash
just sync-all-search-indexes
```

## What the stages do

Each stage is a `manage.py` command you can also run by hand (for example
against a database you restored yourself). All write commands are **dry-run
by default** and only write with `--apply`; every one prints a summary of
what it did or would do.

| # | Stage | Command | What it protects |
|---|---|---|---|
| 0 | Sanity | `SELECT count(*) FROM manuscripts_imagetext` | Refuses an empty or partially loaded dump. |
| 1 | Cutover gate (conditional) | `verify_tei_cutover --min-rows N` | Only runs when the dump still has a populated `content_dpt_legacy` column — see *Which kind of dump do you have?* |
| 2 | Schema | `migrate` | Brings the schema to the current code. Migration `0027` embeds the graph-side `elementid` links into the texts. |
| 3 | Convert | `migrate_imagetext_to_tei --apply` | Rewrites each row to TEI if it round-trips and is well-formed; rows that fail are **left as `data-dpt`** and listed. Already-TEI rows are skipped, so re-runs are no-ops. |
| 4 | Reverse links | `reencode_graph_elementid --apply` | Writes `{refs: [...]}` onto each linked TEXT graph's `elementid`, keeping the original under `legacy_dpt_elementid` (`--reverse` restores it). |
| 5 | Gate: links | `check_text_links` | Exits non-zero if any `corresp` points at a missing graph, a non-TEXT graph, or a graph on another image. |
| 6 | Gate: validity | `verify_tei` | Exits non-zero unless every `content` is well-formed XML — which also catches any row stage 3 could not convert. |

`apps/manuscripts/tests/test_legacy_migration_pipeline.py` runs stages 2–6 on a
tiny legacy corpus and is the executable version of this table.

## Which kind of dump do you have?

- **A DigiPal dump** (most adopters): `content` is `data-dpt` HTML and there
  is no `content_dpt_legacy` column. The cutover gate is skipped; stages 2–6
  run.
- **A dump from an Archetype install that migrated before the retention
  column was dropped**: `content` is already TEI and `content_dpt_legacy`
  holds the pre-migration HTML. Applying the schema step drops that column,
  which is irreversible, so the script first runs `verify_tei_cutover`, which
  passes only if the retained HTML can be regenerated from the TEI (i.e. the
  column carries no information the TEI does not). Pass extra arguments with
  `TEI_CUTOVER_GATE_ARGS`, e.g.
  `TEI_CUTOVER_GATE_ARGS='--migrated-at 2026-05-31 --accept-superseded'`
  after reviewing the rows it reports as edited since the migration.
  Exit codes: **0** safe · **1** a check failed · **2** the column is already
  absent (deliberately non-zero: "already applied" is not "verified safe").

## Reading a failure

**`migrate_imagetext_to_tei` lists failed ids.** Those rows did not convert
losslessly — typically markup that was already broken in DigiPal (an unclosed
span, an attribute quoted inconsistently, pasted Word markup). They are left
as `data-dpt`, and `verify_tei` then fails, so the script stops before writing
the output. Fix the rows in the input (or in a restored scratch copy), then
re-run. To inspect one row's conversion without writing anything:

```bash
python manage.py migrate_imagetext_to_tei --limit 50   # dry run, first 50 rows
```

**`check_text_links` lists `ImageText #N: ref → Graph M …`.** A text references
a region that does not exist, is not a text region, or sits on another image.
Usually a graph deleted in DigiPal after the link was made; remove the
reference or restore the graph. A reference to a *trashed* graph is counted
under `trashed`, not a failure: the trash keeps the link so a restore needs
no replay.

**`verify_tei` lists `ImageText #N: <parser message>`.** The row is not
well-formed XML. Either it is a conversion failure from above, or TEI that was
hand-edited into an invalid state.

## After the migration

- Search: `just sync-all-search-indexes` (the documents copy text content and
  region coordinates, which the migration changed).
- The backoffice editor validates and formats TEI
  (`image-texts/validate-tei/`, `image-texts/format-tei/`); run
  `format_image_text_tei --apply` once if you want the stored single-line
  texts laid out for reading in the source view. It never changes character
  data and re-checks every row after formatting.
- Read-only checks you can run any time: `verify_tei`, `check_text_links`.
- Images: a DigiPal media folder holds TIFFs, but `ItemImage.image` paths
  end in `.jp2` and SIPI serves only what is on disk. Run
  `scripts/convert_tif_to_jp2.py <media root>` once (needs `vips`, runs
  without Django) to write a lossless `.jp2` next to every `.tif`.

## There is no rollback

Once a database is on TEI there is no command that turns it back into
`data-dpt`. Keep the input dump. (`tei_to_data_dpt` in
`apps/manuscripts/services/tei/` can regenerate `data-dpt` from TEI on demand,
and `reencode_graph_elementid --reverse` restores the graphs' original
`elementid`, but neither is a supported migration path.)

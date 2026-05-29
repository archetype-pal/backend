# Legacy `old_arch` To Current Schema Migration Plan

This document explains the transition from the legacy `old_arch` database to
the current Archetype backend schema represented by `test_db`.

It is paired with the read-only audit command:

```bash
docker compose run --rm api python manage.py audit_legacy_migration \
  --format markdown \
  --output docs/legacy-migration-audit.md
```

The command validates the live databases without writing to either one. The
checked-in audit snapshot is [legacy-migration-audit.md](legacy-migration-audit.md).

## Current Comparison Summary

Snapshot: 2026-05-29.

| Database | Public tables | Shape |
| --- | ---: | --- |
| `old_arch` | 142 | Legacy Digipal/Mezzanine/South-era schema. |
| `test_db` | 52 | Current Django app schema. |

The current target is clearly a selective migration, not a full clone:

- Core manuscript, scribe, symbol, image, annotation, text, and publication
  entities were migrated.
- New current-only workflow and product tables exist in the target:
  `common_editevent`, `manuscripts_statustransition`, and `worksets_workset`.
- Current-only derived metadata exists for date assessments in
  `manuscripts_historicalitemdateassessment`.
- Many legacy support tables were intentionally retired: request logs,
  revisions, South migration history, old page/forms/twitter/gallery tables,
  permissions, ratings, and empty legacy vocabularies.
- Most domain entity ids were preserved.
- A few target placeholder rows were introduced with negative ids, notably
  `-1` item part, scribe, and allograph.
- `common_date` keeps legacy ids but also has target-only seed rows `1` to
  `16`.
- Some join tables were re-keyed in the target because they became explicit
  through-models or tagulous tables.

## Entity Mapping

| Legacy entity | Current entity | Migration status |
| --- | --- | --- |
| `digipal_date` | `common_date` | Id-preserved, with target-only seed dates `1` to `16`. |
| none | `common_editevent` | Target-only append-only edit log; do not import from legacy. |
| `digipal_format` | `manuscripts_itemformat` | Direct/id-preserved. |
| `digipal_source` | `manuscripts_bibliographicsource` | Direct/id-preserved. |
| `digipal_repository` | `manuscripts_repository` | Id-preserved; place/type denormalised. Blank labels need explicit fallbacks. |
| `digipal_currentitem` | `manuscripts_currentitem` | Id-preserved; shelfmarks/descriptions transformed. |
| `digipal_historicalitem` | `manuscripts_historicalitem` | Id-preserved; type/language/hair/date lookups flattened. |
| target date metadata | `manuscripts_historicalitemdateassessment` | Target-only derived metadata, currently 22 rows. |
| `digipal_description` | `manuscripts_historicalitemdescription` | Id-preserved; `description` becomes `content`. |
| `digipal_cataloguenumber` | `manuscripts_cataloguenumber` | Id-preserved; `source_id` becomes `catalogue_id`. |
| `digipal_itempart` plus `digipal_itempartitem` | `manuscripts_itempart` | Id-preserved from item part; target has synthetic `-1`. Historical link comes from `digipal_itempartitem`. |
| `digipal_image` | `manuscripts_itemimage` | Id-preserved; image path/IIIF fields transformed. |
| Non-empty `digipal_text_textcontentxml` | `manuscripts_imagetext` | Content-preserved; ids not preserved. Empty XML rows are excluded. Current review fields and `content_dpt_legacy` are target-side additions. |
| none | `manuscripts_statustransition` | Target-only image-text review workflow log; do not import from legacy. |
| `digipal_scribe` | `scribes_scribe` | Id-preserved; target has synthetic `-1`. |
| `digipal_script` | `scribes_script` | Direct/id-preserved; currently zero rows. |
| `digipal_hand` | `scribes_hand` | Id-preserved; legacy display fields collapse into target name/place/description. Current `num`, `priority`, and `is_default` drive ordering/default selection. |
| `digipal_hand_images` | `scribes_hand_item_part_images` | Direct/id-preserved. |
| `digipal_character` | `symbols_structure_character` | Id-preserved; ontograph/form data flattened into type. |
| `digipal_allograph` | `symbols_structure_allograph` | Id-preserved; target has synthetic `-1`. |
| `digipal_component` | `symbols_structure_component` | Direct/id-preserved. |
| `digipal_feature` | `symbols_structure_feature` | Direct/id-preserved. |
| `digipal_component_features` | `symbols_structure_component_features` | Direct/id-preserved. |
| `digipal_allographcomponent` | `symbols_structure_allographcomponent` | Mostly id-preserved; legacy row `46` is absent in the inspected target. |
| `digipal_allographcomponent_features` | `symbols_structure_allographcomponentfeature` | Mostly id-preserved; legacy row `127` is absent in the inspected target. |
| `digipal_aspect` | `symbols_structure_position` | Id-preserved rename. |
| `digipal_allograph_aspects` | `symbols_structure_allographposition` | Re-keyed; row count preserved. |
| `digipal_annotation` plus `digipal_graph` | `annotations_graph` | Legacy annotation ids preserved; target has two extra graph rows. Target `created` is current-side metadata. |
| `digipal_graphcomponent` | `annotations_graphcomponent` | Mostly preserved but filtered. |
| `digipal_graphcomponent_features` | `annotations_graphcomponent_features` | Mostly preserved but filtered. |
| `digipal_graph_aspects` | `annotations_graph_positions` | Re-keyed and filtered with graph rows; six fewer rows in the current target snapshot. |
| `blog_blogpost` | `publications_publication` | Id-preserved; author ids need special handling. |
| `blog_blogpost_categories` | `publications_publication_keywords` | Re-keyed through tagulous keywords. |
| `digipal_carouselitem` | `publications_carouselitem` | Id-preserved; field names transformed. |
| none | `worksets_workset` | Target-only user-saved lightbox/citable collection feature; currently empty. |

## Key Differences And Risks

### Publication Authors

Do not use legacy `auth_user.id` as the publication author key in a fresh
migration. The current target has seeded users in ids `1` to `5`, so migrated
publication rows that kept old author ids now resolve to different usernames
for several authors.

Safe future options:

- Create/map legacy users by username or email before importing publications.
- Or choose one explicit fallback author and record the original legacy author
  username in publication metadata or migration logs.

### Annotations

Legacy annotations are split across:

- `digipal_annotation`: image region, geo JSON, notes, text/editorial type.
- `digipal_graph`: graph classification, hand, idiograph.
- `digipal_idiograph`: allograph indirection.
- `digipal_graphcomponent`, `digipal_graphcomponent_features`,
  `digipal_graph_aspects`: selected components/features/aspects.

The target collapses much of this into `annotations_graph`, with separate
through tables for components/features/positions.

Observed audit facts:

- All 24,584 legacy annotation ids exist in `annotations_graph`.
- The target has two extra annotation rows: `27336`, `27337`.
- Legacy has 20,535 graph-linked image annotations.
- Target has 20,536 `image` graph rows.
- Target has 24,586 total graph rows.
- Target text/editorial graph rows retain `allograph_id`/`hand_id` values.
  This is allowed by the database constraint, but it differs from the current
  model comment that treats those links as optional for text/editorial rows.
- Current target graph rows have `created` populated; legacy data has no
  equivalent creation timestamp.

### Image Text

Legacy text data lives in `digipal_text_textcontentxml`. The migration should
only import non-empty XML content.

Current counts:

- Legacy non-empty XML rows: 899.
- Target `manuscripts_imagetext` rows: 899.
- Empty draft rows are intentionally excluded.
- `review_assignee_id`, `StatusTransition`, and `content_dpt_legacy` are
  current workflow/TEI migration fields, not old_arch source data.

### Current-Only Tables And Metadata

These target structures are valid target data but not legacy imports:

- `common_editevent`: 22 rows in the current snapshot.
- `manuscripts_historicalitemdateassessment`: 22 rows in the current snapshot,
  generated from current target date metadata.
- `manuscripts_statustransition`: 0 rows in the current snapshot.
- `worksets_workset`: 0 rows in the current snapshot.

For a fresh migration, create these through current application workflows or
target-side data migrations only when their source semantics are clear. Do not
manufacture them from old_arch tables without a separate product decision.

### Retired Legacy Tables

These categories should not be imported into the current schema unless a
product requirement reintroduces them:

- Logs/history: `digipal_requestlog`, `reversion_*`,
  `south_migrationhistory`, old `django_session` rows.
- Legacy CMS structures not represented in the current app:
  `pages_*`, `forms_*`, `galleries_*`, `twitter_*`.
- Empty or unsupported palaeographic/manuscript tables such as legacy
  collation, decoration, layout, owners, places, institutions, measurements,
  and provenance tables. Some have data, but there is no current model surface
  for them.
- Legacy permission/group assignments. Rebuild these in the current app
  instead of copying them.

## Safe Future Migration Procedure

Use Docker Compose throughout. Do not run backend database operations directly
against host Python.

1. Backup everything.
   - Dump the legacy database with `pg_dump --format=custom`.
   - Dump the target database before any trial migration.
   - Store both dumps outside the live Postgres volume.

2. Restore legacy side-by-side.
   - Restore legacy into a database named `old_arch`.
   - Create a fresh target database from current Django migrations.
   - Do not import into a target database with existing domain rows unless the
     task is explicitly an audit.

3. Run the read-only audit.
   - Use `audit_legacy_migration`.
   - Treat `fail` as a blocker.
   - Treat `warn` as requiring sign-off, because warnings identify intentional
     loss, placeholders, or transformed semantics.

4. Import in dependency order.
   - Users/authors or fallback author policy.
   - Core vocabularies: dates, formats, sources, repositories.
   - Symbol vocabularies: characters, allographs, components, features,
     positions.
   - Manuscript entities: current items, historical items, descriptions,
     catalogue numbers, item parts, images.
   - Scribes and hands.
   - Image text.
   - Annotations and graph through tables.
   - Publications, comments if any, carousel items, keywords.
   - Target-only workflow/product tables only after the migrated data is
     validated, and only from current-system sources.

5. Preserve ids where the audit says ids are preserved.
   - This keeps legacy URLs/references easier to reconcile.
   - Reset sequences after importing explicit ids.
   - Keep negative placeholder ids explicit and documented.

6. Validate after each phase.
   - Re-run `audit_legacy_migration`.
   - Check row counts and samples.
   - Check FK integrity.
   - Check target constraints.
   - Run focused application tests.

7. Rebuild derived systems.
   - Run migrations.
   - Run `just sync-sequences`.
   - Rebuild Meilisearch indexes with `just sync-all-search-indexes`.
   - For image text TEI work, keep `content_dpt_legacy` as the reversible
     source during the retention window.

8. Record an import manifest.
   - Legacy dump filename and checksum.
   - Target schema migration state.
   - Audit output.
   - Any accepted warnings.
   - Any rows intentionally skipped.

## Commands

Read-only audit to Markdown:

```bash
docker compose run --rm api python manage.py audit_legacy_migration \
  --format markdown \
  --output docs/legacy-migration-audit.md
```

By default the command uses `DATABASE_URL`/`TARGET_DATABASE_URL` for the
current database and derives `old_arch` by changing only the database name. If
you pass `--target-url` and omit `--legacy-url`, `old_arch` is derived from
that target URL. Set both URLs explicitly when auditing a non-standard restore
or remote database.

Machine-readable audit:

```bash
docker compose run --rm api python manage.py audit_legacy_migration \
  --format json \
  --output /tmp/legacy-migration-audit.json
```

CI-style strict audit:

```bash
docker compose run --rm api python manage.py audit_legacy_migration \
  --fail-on-warning
```

## Implementation Notes

The current command is deliberately read-only. It is the validation layer that
should guard any future write importer.

A safe write importer should be added as a separate command only after the
warning policies above are accepted. That importer should:

- Require an empty target database unless explicitly running in audit mode.
- Use transactions per phase.
- Preserve ids for id-preserved mappings.
- Refuse to proceed on unmapped required foreign keys.
- Require an explicit publication author policy.
- Save an import manifest and final audit output.
- Refuse to run if `legacy_url` and `target_url` point at the same database.

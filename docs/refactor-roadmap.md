# Refactor roadmap

A cleanup plan for the backend after months of feature work without a
consolidation pass. It is ordered so every phase is independently shippable,
starts with zero-risk deletions, and ends with the structural changes that
need the earlier phases in place.

Audit basis: every non-test module under `apps/`, `config/` and `scripts/`
was read; cross-references were checked mechanically (every `def`/`class`
in non-test code grepped against the rest of the tree); the URL tree was
enumerated from a live `django.setup()`; the test suite was run on SQLite
(917 pass — the 82 failures observed were all the audit sandbox's stale
`djiiif 1.x`, not code defects).

---

## 0. Where the codebase stands

**What is good and must be preserved**

- Clear feature-app layout with an enforced dependency graph
  (`scripts/check_architecture_boundaries.py`).
- A genuinely declarative search stack: `registry.py` + `dependencies.py`
  + atomic build-and-swap reindex. This is the best-designed part of the
  code; the roadmap touches only its edges.
- Reusable view bases in `apps/common/views.py` (`*PrivilegedViewSet`,
  `ActionSerializerMixin`, `StableOrderingFilter`, `TrashableViewSetMixin`)
  and a working soft-delete + audit-log foundation.
- Strong tests (~1,000), factories per app, query-count regression tests.
- Comments explain *why*, with issue references. Keep that habit.

**What has drifted**

| Symptom | Where it shows |
|---|---|
| Business logic in views, against the project's own guardrail | `manuscripts/views.py` (1,137 lines, 24 write operations), `common/views.py` (726 lines; serializers, settings data and transforms inside the view module) |
| Copy-pasted blocks instead of a shared helper | search document builders (4× identical `shared` dict), TEI link rewriters (3× identical HTMLParser boilerplate), IIIF dimension resolution (2×), publications image fields (2×), `_display_label` (3×) |
| Dead or redundant surface | `manuscripts/widgets.py`, `FilterSpec.in_`, duplicate orchestration/task pairs, unused service wrappers, a redundant endpoint |
| Modules living in the wrong app | `search/quality_endpoints.py`, `search/text_monitoring_endpoints.py` (dashboards over DB tables, nothing to do with search) |
| A service importing from a view | `common/services/branding.py` → `common/views.py` |
| Hand-rolled request parsing | 19 `request.data.get(...)` + manual `isinstance` checks in `manuscripts/views.py` alone, mixed literal `status=400` and `status.HTTP_400_BAD_REQUEST` |
| Historical narration baked into code | ~60 "Phase H.3 / Track C2 / M5.2 / TEI-descriptions 7.1" references, 6 pointers to a `docs/tei.md` that does not exist in this repo |
| Migration tooling written for one run, but needed by every adopter | The DigiPal→TEI pipeline (5 commands + script + runbook) assumes the original operator's context; other installs must go through it too |

---

## 1. Findings in detail

### 1.1 Dead code (safe to delete)

| Item | Evidence |
|---|---|
| `apps/manuscripts/widgets.py` (`ImagePickerWidget`, 133 lines of inline HTML/JS) | Zero references anywhere. `django.contrib.admin` is not installed, so a form widget has no host. |
| `apps/manuscripts/iiif.py:11-13` | `logger = logging.getLogger(__name__)` declared twice. |
| `FilterSpec.in_` (`search/types.py`) and its branches in `filters.py`, `filter_contract.sanitize_filter_spec`, `parsers._merge_filter_with_qb` | Nothing ever populates it; `equal` with a list value already has the same OR semantics. |
| `SearchAdminService.resolve_index_type`, `SearchAdminService.clear_index` | Pure pass-throughs, no callers (views, tasks and commands call the orchestration service directly). |
| `MeilisearchIndexWriter.replace_documents` | Only used by `tests/test_search_api.py` as a fixture loader; not part of any production path (reindex uses the build/swap methods). Move into the test helper or delete. |
| `apps/common/migrations/__init__` (extensionless empty file) | Stray artifact next to the real `__init__.py`. |
| `IndexType.from_url_segment` / `to_url_segment` lazy imports of `registry` | `url_segment` is `value.replace("_", "-")`; the lazy circular import exists only to read that. Compute it on the enum and drop the cycle. |
| `check_meilisearch_health` in `search/admin_service.py` | Duplicates `common.services.sanity_checks.check_meilisearch` (the latter even documents that it does). Keep one. |

### 1.2 Redundant API / task surface

| Redundancy | Detail |
|---|---|
| `SearchOrchestrationService.clear_and_reindex_index` ≡ `reindex_index` | Identical bodies (the docstring admits it). Same for Celery tasks `clean_and_reindex_search_index` ≡ `reindex_search_index` (only the `action` label differs) and `reindex_all` ≡ `clear_and_reindex_all` minus a reporter. `docs/search-operations.md` already warns "despite their names … do not clear first". Keep one implementation, keep the old action names as aliases at the HTTP boundary if the frontend still sends them. |
| `GET management/scribes/get_item_images/?item_part_id=` (`HandItemImagesForManagement`) | Same data as `GET management/item-images/?item_part=` which already exists. Retire after the frontend switches. |
| Five `DefaultRouter()` instances mounted at `api/v1/` | Produces five `APIRootView`s on one path and doubles the route table with `.json` format-suffix variants nobody uses. Use `SimpleRouter` everywhere (as `uploads` already does) or one shared router. |
| `management/image-picker-content/` | Its only in-repo consumer was the dead widget. Documented in `manuscripts/schema.yaml`; confirm with the frontend before removing. |
| `AllographListView` `?light=1` vs a separate summary endpoint | Minor; fine to keep, but it hand-rolls `get_serializer_class` instead of reusing `ActionSerializerMixin`. Same in `WorksetViewSet`. |

### 1.3 Duplicated code (consolidate)

1. **Text-derived search documents** — `search/documents/texts.py`,
   `clauses.py`, `people.py`, `places.py` each rebuild the same ~30-line
   `shared` dict (repository, shelfmark, date triple, catalogue numbers,
   locus, type, status, thumbnail). One `text_context(image_text) -> dict`
   in `documents/utils.py`; `people.py` and `places.py` are then the same
   function parameterised by (extractor, id prefix, type key).
2. **`_display_label`** — defined three times (`item_parts.py`,
   `item_images.py`, `graphs.py`) with the same body modulo the path to the
   part. One helper taking the `ItemPart`.
3. **TEI link rewriters** — `services/tei/links.py`: `_RefAdder`,
   `_RefRemover`, `_RefRemoverAt` repeat `handle_endtag/handle_data/
   handle_entityref/handle_charref/handle_comment` and the `_emit_start`
   skeleton verbatim; `_DptToTeiRewriter`/`_TeiToDptRewriter` share another
   copy of the stack-buffer pattern, and `embed_annotation_ids.
   _SpanAnnotationRewriter` a third. One `_VerbatimRewriter(HTMLParser)`
   base with a single overridable `rewrite_start_tag(tag, attrs)` hook.
4. **IIIF dimension fan-out** — the `ThreadPoolExecutor` block resolving
   `(width, height)` per distinct identifier is copied between
   `annotation_standards/manifest.py` and `content_search.py`. Extract
   `resolve_dimensions_for(images, dims)` next to `resolve_image_dimensions`.
5. **`image_identifier`** (`annotation_standards/helpers.py`) vs
   `get_image_identifier` (`manuscripts/iiif.py`) — same job, different
   fallback (`None` vs `str(image)`). Keep one, decide the fallback once.
6. **CORS header set** — written twice, in `helpers.apply_cors_headers` and
   inline in `IIIFCorsPreflightMiddleware`. Middleware should call the helper.
7. **`ImagePathOrUploadField` / `LogoPathOrUploadField`**
   (`publications/serializers.py`) — identical nested classes; one
   module-level field.
8. **Author display name** — `publications/serializers._author_display_name`
   and `services.create_signed_in_comment` both implement
   `full_name or username`.
9. **`_kind_from_slug`** (`manuscripts/views.py`) — a dict lookup on
   `ImageText.Type` would do; the two `sole_image_text` function views
   duplicate the 404/400 handling the viewsets already provide.
10. **`has_text/has_transcription/has_translation` filters**
    (`ItemImageManagementViewSet.filter_queryset`) and `language=__unset__`,
    `empty=` (`ImageTextManagementViewSet.filter_queryset`) — six near-identical
    `Exists()` branches. Express as a `django_filters.FilterSet` with
    `BooleanFilter(method=...)`, which also makes them discoverable in the
    schema.
11. **`sanitize_filter_spec`** runs twice per request — once in
    `parsers._parse_filter_spec` and again inside
    `meilisearch/filters.build_meilisearch_filter`. Run it once at the
    boundary (the parser) and let the adapter trust its input.
12. **`DEFAULT_SITE_FEATURES`** exists in three places by design (frontend,
    migration 0010, `common/views.py`) — acceptable, but the backend copy
    belongs in a data module, not the view file.
13. **Test-side**: 22 `setUp` methods re-create `APIClient()` +
    `SuperuserFactory()` + `force_authenticate` that the `management_client`
    fixture in `conftest.py` already provides. Unify on the pytest fixtures.

### 1.4 Misplaced modules and layering inversions

| Problem | Fix |
|---|---|
| `apps/search/quality_endpoints.py` and `text_monitoring_endpoints.py` query `ImageText`/`Graph`/`Hand` directly and never touch Meilisearch. Their docstring even claims a `/manuscripts/management/quality/` URL they are not mounted at. | Move to `apps/manuscripts/` (e.g. `views_dashboards.py` + `services/dashboards.py`), mount under `manuscripts/management/`. Keep the old `search/management/...` paths as redirects for one release. |
| `apps/common/services/branding.py` imports `SITE_FEATURES_KEY_PREFIX` from `apps/common/views.py` | Move the site-features key constants, `flatten_settings`/`unflatten_settings`, `DEFAULT_SITE_FEATURES` and the read/write logic into `common/services/site_features.py`; the view keeps HTTP mapping only. |
| `common/views.py` defines seven serializers (`StrictSerializer`, `ThemeWriteSerializer`, …) | Move to `common/serializers.py` (which exists and holds two). |
| `manuscripts/views.py` imports `hand_attribution_error` from `serializers/management.py` | It is a domain rule; it belongs in `manuscripts/services/` and both the serializer and the view import it from there. |
| Migration `manuscripts/0027_embed_text_region_links.py` imports parsing code from a management command | A migration must not depend on a command module that the roadmap retires. Inline the two helpers it needs (or move them into `services/tei/`) so the command can go. |
| `apps/search/registry.py` imports `Graph` and `ImageText` models only for two constants | Use string lookups (`"Live"`) or move `_PUBLIC_TEXT_STATUSES` next to the model's `visible_to` so search and the public API share one definition of "public". |

### 1.5 Views carrying orchestration (against CONTRIBUTING's guardrail)

`apps/manuscripts/views.py::ImageTextManagementViewSet` holds the
status-transition workflow, region link/unlink (three variants), HTR import,
bulk actions and CSV/JSON export — roughly 480 lines of domain logic with
hand-rolled validation. `sole_image_text`/`upsert_sole_image_text` do the
same at module level. Each of these should become:

- an input serializer (`TransitionSerializer`, `LinkRegionSerializer`,
  `UnlinkRegionSerializer`, `UnlinkElementSerializer`, `ImportHtrSerializer`,
  `BulkActionSerializer`, `ImageTextUpsertSerializer`), replacing the
  `isinstance(...)`/`status=400` chains; and
- a function in `manuscripts/services/image_texts.py` (`transition_text`,
  `link_region`, `unlink_region`, `unlink_element`, `import_htr`,
  `bulk_transition`, `bulk_set_language`, `export_rows`) wrapped in the
  transaction + `audit_actor` it needs.

Same treatment, smaller scale: `_msdesc_tei_response` (a service that
returns an `HttpResponse`), `SiteLabelsView.put` (ad-hoc dict validation;
should be a serializer), `search/views_search.py` `_to_bibtex`/CSV writers
(a `search/exports.py`), `CommentManagementViewSet.approve/reject` (one
`set_approved(comment, bool)`).

### 1.6 Latent bugs found while reading

- `manuscripts/serializers/public.py`: `CatalogueNumberSerializer.catalogue`
  and `HistoricalItemDescriptionSerializer.source` use `RepositorySerializer`
  for a `BibliographicSource`. It only "works" because DRF skips the missing
  `place` and nulls the missing `url`. Add a `BibliographicSourceSerializer`
  (`name`, `label`) — this changes the public payload shape, so coordinate
  with the frontend.
- `manuscripts/views.py::upsert_sole_image_text` stores `content`/`language`
  from `request.data` without any serializer — no max length, no type check
  (a list would be stored as `str(list)`). Fixed by 1.5.
- `GraphViewerWriteViewSet` restricts `http_method_names` but the router
  still publishes `list`/`retrieve` routes that 405; register with
  `viewsets.GenericViewSet` + the three mixins instead of `ModelViewSet`.
- HTR import (`import_htr`) and TEI validation parse caller-supplied XML
  with stdlib `xml.etree`. `defusedxml` is already an installed transitive
  dependency; use it for untrusted input.
- `apps/search/documents/utils.annotation_coordinates_map` has a
  `hasattr(graphs, "only")` guard for a queryset — a leftover from a mock;
  remove.

### 1.7 The DigiPal → Archetype migration tooling

`apps/manuscripts/management/commands/` holds seven commands. Five of them
(`migrate_imagetext_to_tei`, `verify_tei_cutover`, `reencode_graph_elementid`,
`embed_annotation_ids`, `format_image_text_tei`), together with
`services/tei/tei_to_data_dpt.py`, `canonical_data_dpt`,
`contains_tei_element`, `scripts/migrate_backup_to_tei.sh` and
`docs/tei-backup-migration.md`, form the pipeline that brings a legacy
DigiPal/data-dpt database up to the current TEI storage.

**This pipeline is a supported surface, not legacy.** Other institutions run
DigiPal-era databases and will go through the same migration when they adopt
this project. It stays in the app tree, runnable from `manage.py`, with its
tests. What needs work is how approachable it is for someone who was not
here when it was written:

- The runbook defers to a superproject `docs/tei.md §5.3` that a backend
  clone does not have, and reads like an internal one-off ("the May TEI
  migration", "in production since 2026-08-29", "H.11 cutover") rather than
  an adopter's guide.
- The pipeline assumes the operator knows the order of steps and the
  meaning of each gate; the only entry point is a bash script whose
  prerequisites (compose stack, plain-SQL dump, `config/.env`) are spread
  across comments.
- `verify_tei_cutover` exists to protect a column (`content_dpt_legacy`)
  that any new adopter's dump either has populated or has never had; the
  README should say plainly which case applies to them.
- Migration `0027_embed_text_region_links.py` imports helpers from the
  `embed_annotation_ids` command module, so the command and the migration
  must evolve together — that coupling should be explicit or removed.
- `search/documents/dpt_parser.py` still parses TEI by converting it back to
  data-dpt via `tei_to_data_dpt`. That keeps the reverse converter on the hot
  path of every reindex; a TEI-native extractor would decouple search from
  the migration tooling (the converter itself stays, for the migration).

### 1.8 Hygiene / consistency

- `GenericViewSet, ListModelMixin, RetrieveModelMixin` spelled out in eight
  places where `ReadOnlyModelViewSet` exists.
- `status=400` / `status=404` literals vs `status.HTTP_*` (6 places).
- Mixed relative and absolute imports within one module
  (`publications/views.py` imports `Comment` absolutely and the rest
  relatively).
- `import json` inside a function body (`manuscripts/views.py` export).
- Inconsistent test styles: `unittest.TestCase` + `setUp` alongside pytest
  fixtures, in the same apps.
- Comments that narrate project history ("Phase G", "Track A", "M5.2",
  "TEI-descriptions 7.1", "H.11 checklist item 4") instead of the rule
  itself; six references to `docs/tei.md` and two to `KNOWLEDGEBASE.md`,
  neither of which exists here. Keep the *reason*, drop the phase label, and
  either vendor the referenced doc into `docs/` or link to where it lives.
- `apps/search/` and `apps/annotation_standards/` have no `schema.yaml`;
  the existing files miss ~60 real routes (every `{id}/` detail route of
  the scribes/symbols/media management viewsets, all `image-texts` actions,
  the IIIF/W3C endpoints) while documenting per-type `/search/<type>/facets/`
  paths that do not resolve. `test_schema_yaml_consistency` only checks one
  direction; add the reverse check (every route is documented) once the
  files are complete, or reconsider generating the schema.
- `config/settings.py` `TEMPLATES["DIRS"]` and `STATICFILES_DIRS` point at
  `BASE_DIR/templates` and `BASE_DIR/static`, neither of which exists
  (warning on every boot).
- `pyproject.toml` lists `idna`, `pyjwt`, `cryptography`, `python-dateutil`
  as direct dependencies; none is imported by non-test code (`dateutil` is
  used by one test factory). If they are there as CVE floors, say so in a
  comment (as is done for `social-auth-app-django`); otherwise let them be
  transitive and move `python-dateutil` to the dev group.

---

## 2. The roadmap

Each phase is a PR series that leaves `main` green. Effort is a rough
engineer-days estimate. "Contract" flags what the frontend has to know.

### Phase 1 — Delete (0 risk, ~1 day) — DONE

What landed:

1. §1.1 removals: `manuscripts/widgets.py`, the duplicate logger in
   `manuscripts/iiif.py`, the stray `common/migrations/__init__`,
   `FilterSpec.in_` and its three dead branches, `SearchAdminService.
   {resolve_index_type, clear_index, check_meilisearch_health}` (the stats
   view now uses `common.services.sanity_checks.check_meilisearch`),
   `MeilisearchIndexWriter.replace_documents` and its unused `BATCH_SIZE`
   (the only caller was a test fixture, which now seeds through the public
   writer API), and the `IndexType` ↔ `registry` circular lazy import
   (`to_url_segment` is computed on the enum; `URL_SEGMENT_TO_INDEX_TYPE`
   is gone).
2. Orchestration/task dedup: `SearchOrchestrationService` keeps
   `clear_index`, `reindex_index`, `reindex_all(reporter=)`,
   `setup_all_indexes`; Celery keeps `reindex_search_index`,
   `clear_search_index`, `reindex_all_search_indexes`. The management API
   still accepts `clean_and_reindex` and `clear_and_rebuild_all` as action
   names (both dispatch the plain reindex task). **Contract note:** the
   task-status `result.action` for those two is now `"reindex"` /
   `"reindex_all"` instead of echoing the alias. Docs updated.
3. Every app router is a `SimpleRouter`: the five stacked `api/v1/` API
   roots and all `.json` format-suffix routes are gone (289 → 156 URL
   patterns; no test or schema referenced them).
4. `TEMPLATES["DIRS"]` and `STATICFILES_DIRS` no longer point at directories
   that do not exist (the boot-time `staticfiles.W004` warning is gone).
5. `GraphViewerWriteViewSet` is now `Create/Update/DestroyModelMixin +
   GenericViewSet` instead of a `ModelViewSet` with reads masked; it keeps
   `http_method_names` without PUT because `schema.yaml` documents only
   PATCH on that route.

Not done here — needs a machine with `uv` and network access:
- prune/justify the direct dependencies in `pyproject.toml` (§1.8), because
  `uv lock --check` in CI requires the lockfile to be regenerated alongside.

Verification: suite run on SQLite, same pass set as before the change (the
only delta is the removed `clean_and_reindex` task test); `scripts/
check_architecture_boundaries.py` clean; schema-consistency tests clean.

### Phase 2 — Consolidate duplicates (low risk, ~3 days)

In dependency order so each step is a small diff:

1. `search/documents/utils.py`: `text_context()` + single `display_label()`;
   rewrite `texts/clauses/people/places/graphs/item_images/item_parts`
   builders on top. `test_document_builders.py` already pins every output
   shape — the tests are the safety net, no new ones needed.
2. `services/tei/links.py` + `data_dpt_to_tei.py` + `tei_to_data_dpt.py`:
   introduce `_VerbatimRewriter`. Round-trip and link tests
   (`test_tei_converters.py`, `test_tei_links.py`) cover it.
3. `manuscripts/iiif.py`: `resolve_dimensions_for()`; single
   `get_image_identifier`; delete `annotation_standards/helpers.
   image_identifier`. Middleware uses `apply_cors_headers`.
4. `publications`: one `ImagePathOrUploadField`; one `author_display_name`
   in services.
5. Run `sanitize_filter_spec` once (parser) — drop the call in
   `build_meilisearch_filter`.
6. `ItemImageManagementViewSet` / `ImageTextManagementViewSet` ad-hoc
   filters → `FilterSet` classes with `method=` filters.
7. Replace the spelled-out read-only viewset bases with
   `ReadOnlyModelViewSet`; `WorksetViewSet`/`AllographListView` on
   `ActionSerializerMixin`.

### Phase 3 — Put things where they belong (medium risk, ~3 days)

1. `common`: create `services/site_features.py` and move the key constants,
   flatten/unflatten, defaults and the GET/PUT logic; move the seven
   serializers to `serializers.py`; `branding.py` imports from the service.
   `common/views.py` shrinks to transport.
2. Move `quality_endpoints.py` and `text_monitoring_endpoints.py` to
   `manuscripts` (views + `services/dashboards.py`), mounted at
   `manuscripts/management/quality/` and
   `manuscripts/management/image-texts/overview/`. Keep
   `search/management/quality/` and `…/image-texts/overview/` as 308s for
   one release. Contract: frontend updates two URLs.
3. `hand_attribution_error` → `manuscripts/services/images.py`.
4. Migration 0027: inline the two helpers it imports from the command.
5. Retire `HandItemImagesForManagement` once the frontend uses
   `management/item-images/?item_part=`. Contract.

### Phase 4 — Thin the fat views (medium risk, ~5 days)

`manuscripts/views.py` is the target; do it one action per PR so reviews
stay small and each lands with its serializer + service + unchanged tests:

1. `transition` and `bulk_action("transition")` → `services/image_texts.
   transition_text()` (one implementation for single and bulk).
2. `link_region` / `unlink_region` / `unlink_element` → `link_region()`,
   `unlink_region()`, `unlink_element()`; the `pre_delete` signal in
   `manuscripts/signals.py` calls the same `strip_region_refs()`.
3. `import_htr` → `services/htr/import_.py::import_htr()`.
4. `export` → `services/image_texts.export_rows()` + a tiny CSV/JSON writer
   shared with `search/exports.py` (which also takes `_to_bibtex` and
   `_csv_*` out of `views_search.py`). `_csv_safe` becomes the one CSV
   injection guard for both.
5. `sole_image_text` / `upsert_sole_image_text` → actions on
   `ImageViewSet` / `ItemImageManagementViewSet` with a serializer, or a
   dedicated `SoleImageTextView` with `ImageTextUpsertSerializer`.
6. `_msdesc_tei_response` → `services/tei/export.py::build_msdesc_document
   (part, published_only) -> (document | errors)`; the two `tei` actions
   map the result to HTTP.
7. Split the module: `views/public.py`, `views/management.py`,
   `views/image_texts.py` (mirrors the existing `serializers/` split).
8. `SiteLabelsView.put` and `search_action` get serializers.

Acceptance: no `request.data.get(` left in `apps/*/views*.py`; no
`transaction.atomic` in a view; `manuscripts/views/*.py` each < 400 lines.

### Phase 5 — Make the DigiPal migration easy to pick up (low risk, ~3 days)

The goal is that a new adopter with a DigiPal-era dump can migrate it by
following one document, without reading the command sources.

1. **Rewrite `docs/tei-backup-migration.md` as an adopter's guide**, self-
   contained (no pointer to an external `docs/tei.md`): what a legacy
   database looks like (`data-dpt` spans, graph-side `elementid` links),
   prerequisites, the one-command path, what each stage does and what its
   gate protects, how to read each failure, what to do with rows reported
   as non-round-tripping, and the post-restore reindex. Drop the project-
   internal dating ("May migration", "H.11"); say which dump shapes need the
   cutover gate and which do not.
2. **Add a `migrate_legacy_database` umbrella command** (or a `--dry-run`
   mode on the shell script) that runs the stages in order with a summary
   report, so the bash script becomes a thin wrapper and the pipeline is
   also runnable on Windows/without compose.
3. **Harden the entry points**: consistent `--dry-run`/`--apply` flags and
   exit codes across the five commands (today `embed_annotation_ids` and
   `reencode_graph_elementid` differ), a `--report FILE` option writing the
   per-row failure list that the runbook tells operators to review.
4. **Decouple migration 0027 from the command module** (move the two parsing
   helpers into `services/tei/` and import them from both).
5. **Add a fixture-based end-to-end test** of the pipeline on a tiny legacy
   dataset (a handful of `ImageText` rows with data-dpt spans and graphs
   carrying `elementid`), asserting the migrated TEI, the embedded `corresp`
   links and the gate outcomes — the contract an adopter relies on.
6. Sweep comments: remove phase/track labels, fix the `docs/tei.md` and
   `KNOWLEDGEBASE.md` references, make the `content_dpt_legacy` narration
   describe the two dump shapes rather than the project's history.
7. Optional: TEI-native extractor in `search/documents/` so reindexing no
   longer goes through `tei_to_data_dpt` (requires a `PARSER_VERSION` bump
   and a reindex).

### Phase 6 — Contract and documentation (ongoing, ~2 days)

1. Add `apps/search/schema.yaml` and `apps/annotation_standards/schema.yaml`;
   complete the missing detail/action routes in the others; fix the
   per-type facets paths. Then extend `test_schema_yaml_consistency.py` with
   the reverse check (every resolvable `api/v1` route is documented) so
   coverage cannot regress.
2. Fix the `CatalogueNumber`/`Description` source serializer (§1.6) with a
   frontend-coordinated release note.
3. Normalise test style on pytest fixtures (`management_client`,
   `authenticated_client`); delete the `setUp` boilerplate.

---

## 3. Guardrails to add so this does not recur

- **Dead-code check in CI**: `uvx vulture apps config --min-confidence 80`
  with a small allow-list (signal receivers, `AppConfig`, settings). Cheap,
  and it would have flagged `widgets.py`, `in_` and the unused
  service wrappers.
- **Ruff rules**: enable `C4` (comprehensions), `SIM` (simplify), `PL`'s
  `PLR0915`/`PLR0912` with generous limits (too-many-statements/branches)
  to flag the next 100-line view action, and `TID252` to ban relative
  imports (or the opposite — pick one style).
- **Architecture check**: extend `check_architecture_boundaries.py` with an
  intra-app rule — `services/` and `serializers/` may not import from
  `views`. One regex, mirrors the existing `config` rule.
- **Review checklist line** (CONTRIBUTING): "a new `@action` ships with an
  input serializer and a service function; the view body maps one to the
  other".
- **No new phase labels in comments**: keep the reason and the issue link;
  the roadmap phase is git history.

---

## 4. Quick reference — files by action

| Action | Files |
|---|---|
| Delete | `manuscripts/widgets.py`, `common/migrations/__init__`, `FilterSpec.in_` branches, `SearchAdminService.{resolve_index_type,clear_index,check_meilisearch_health}`, `MeilisearchIndexWriter.replace_documents`, `SearchOrchestrationService.{clear_and_reindex_index,clear_and_reindex_all}`, tasks `clean_and_reindex_search_index`/`clear_and_reindex_all_search_indexes` |
| Merge into one helper | text-document `shared` dicts, `_display_label`×3, HTMLParser rewriters×6, dimension fan-out×2, `image_identifier`×2, CORS headers×2, `*PathOrUploadField`×2, author display name×2, `sanitize_filter_spec` double call |
| Move | `search/quality_endpoints.py` → manuscripts; `search/text_monitoring_endpoints.py` → manuscripts; site-features logic + serializers out of `common/views.py`; `hand_attribution_error` → services; bibtex/csv out of `views_search.py` |
| Rewrite with serializer + service | `ImageTextManagementViewSet.{transition,link_region,unlink_region,unlink_element,import_htr,bulk_action,export}`, `sole_image_text`, `upsert_sole_image_text`, `SiteLabelsView.put`, `search_action` |
| Fix | `CatalogueNumberSerializer.catalogue`, `HistoricalItemDescriptionSerializer.source`, `GraphViewerWriteViewSet` base, settings `DIRS`, `defusedxml` for HTR/TEI input |

# Search architecture

This document is the map of the search stack. Day-to-day operational
commands (sync an index, reindex everything, watch a task) live in
[`search-operations.md`](./search-operations.md). This one is for
understanding *why* the modules are shaped the way they are when you
need to add an index type, swap the backend, or change how progress
gets reported.

## Stack at a glance

- **Backend**: Meilisearch (1.x). Talked to via the `meilisearch`
  Python SDK, hidden behind the `SearchBackend` Protocol in
  `apps/search/contracts.py` so any future swap (Typesense, OpenSearch,
  …) only needs a new adapter under `apps/search/<vendor>/`.
- **Indexing**: Celery tasks → application service → indexing service
  → writer adapter. Each layer has a single responsibility.
- **Search**: HTTP request → DRF view → application service → reader
  adapter → Meilisearch. Query parameters are parsed into typed
  `SearchQuery` objects so the backend never sees raw query strings.

## The registry is the single source of truth

`apps/search/registry.py` maps every `IndexType` (the enum in
`apps/search/types.py`, e.g. `ITEM_PARTS`) to one `IndexRegistration`
holding:

- The Django model it indexes. (The enum value is the Meilisearch uid;
  `IndexType.segment` is the hyphenated form the API, CLI and task payloads
  use, `IndexType.from_segment` the way back.)
- The **builder** callable that turns one ORM object into one or more
  documents (`apps/search/documents/<type>.py`).
- The filterable / sortable / searchable / facet attribute lists used
  when applying Meilisearch settings.
- Which rows are indexed at all (`queryset_filter` / `queryset_exclude`).
  The search endpoints are public and the index cannot filter per user, so
  anything not for everyone stays out of the index: the `ItemPart` pk=-1
  import sentinel, image texts that are not Live or Reviewed, and editorial
  graphs.

When you add a new index type, the registry is the file you edit
first. Everything else — tasks, views, the management commands' index
argument — discovers the new entry through `INDEX_REGISTRY` and
`IndexType`.

The registry also owns `get_queryset_for_index(index_type)`. Each index's
row filter and query optimization (`select_related` / `prefetch_related`)
is declared *on its `IndexRegistration` entry* and applied generically
here — there is no per-type branch. Builders trust the queryset is already
shaped for their access pattern; they don't add their own `select_related`.

## Data flow: indexing

```
                     ┌─ tasks.py (Celery entry point)
                     │  • reindex_search_index(segment)
                     │  • clear_search_index(segment)
                     │  • reindex_all_search_indexes()
                     │
                     ▼
                 IndexingService                       services.py
                     │  • reindex(IndexType): iterates the registry queryset
                     │    in batches, atomic build-and-swap (see below),
                     │    per-batch progress reports
                     │  • reindex_all(): the outer loop over every index
                     │
                     ▼
                 MeilisearchIndexWriter                meilisearch/writer.py
                     • prepare_build_index, add_documents_to_build,
                       swap_with_build, drop_build_index, …
```

### Atomic build-and-swap

`IndexingService.reindex` does **not** mutate the live index in place.
Instead:

1. Create a staging index `<uid>__build` with the same Meilisearch
   settings as live.
2. Stream documents into staging in batches of
   `REINDEX_BATCH_SIZE = 500`.
3. Atomically swap `<uid>` ↔ `<uid>__build` (Meilisearch's
   `swap_indexes` API).
4. Drop the orphaned `<uid>__build`.

If the rebuild crashes between steps 2 and 3, the live index keeps
serving the previous (consistent, possibly slightly stale) snapshot
instead of a half-empty one. The next rebuild discards the orphaned
build index on its way through `prepare_build_index`. Retrying a failed
reindex is therefore safe: nothing observable changes until the swap
succeeds.

Two rebuilds of the same index would share one `__build`, so
`reindex_lock` (in `services.py`) holds a per-index key in the Redis
`locks` cache for the duration, and a second rebuild fails with
`ReindexInProgressError`. The key expires after an hour. If Redis is
unreachable the lock is skipped rather than blocking the rebuild.

This is the only place in the search stack with non-trivial recovery
semantics. Don't replace it with an "in-place delete-then-add" loop —
that is the failure mode this is designed to avoid. It is also why there
is no separate "clear and reindex" operation: the management API still
accepts the `clean_and_reindex` and `clear_and_rebuild_all` action names
for existing clients, but both dispatch the same reindex task.

### Incremental sync on model writes

The rebuild above is the bulk path. Day to day, a model write keeps the live
index current on its own:

```
    post_save / pre_delete           apps/search/signals.py
            │
            ▼
    DEPENDENCIES[model]              apps/search/dependencies.py
            │  • which indexes this write invalidates
            │  • a resolver returning the source rows to rebuild
            ▼
    transaction.on_commit → _enqueue in chunks of 500
            │
            ▼
    sync_search_documents(segment, pks)              tasks.py
            │
            ▼
    IndexingService.update_documents_by_ids          services.py
            • re-reads through get_queryset_for_index, so the
              registration's queryset_filter / queryset_exclude apply
            • rows the queryset no longer returns are deleted
```

Two consequences worth knowing:

- **One call covers add, update and remove.** Because documents are rebuilt from
  a queryset rather than from a payload, a row that leaves the queryset — soft
  deleted, hard deleted, or excluded by the registration's filter — has its
  documents removed. That is what makes an `ImageText` moving between Draft and
  Live move its documents with it, and a graph made editorial leave the
  `graphs` index.
- **Documents copy related values, so a write fans out.** A graph document
  carries its hand's name, its scribe's name and its repository, so renaming a
  hand invalidates documents in the `graphs` index too. `dependencies.py` is the
  declaration of that, and it covers every model whose values a document copies
  — the manuscript spine (historical item, current item, repository, date), the
  palaeographic taxonomy (allograph, character, component, feature, position)
  and the bibliographic one (catalogue number, source, format). Blast radius is
  not a reason to leave one out: the largest, a repository rename, resolves into
  chunks in hundredths of a second and rebuilds fewer documents than the full
  reindex it would otherwise need.

  **Adding a field to a builder means adding its source here.** Nothing enforces
  it, and a missing entry is invisible — the document simply keeps the old value
  until someone reindexes.

Deletes listen on `pre_delete`, not `post_delete`, and materialise their ids
there. Django's delete collector runs its `SET_NULL` updates *between* the two
signals, so a resolver running any later finds nothing and those documents keep
a deleted row's values for good.

`Graph` and `GraphComponent` keep hand-written receivers rather than an entry in
the map: one graph write fans out into many component writes in the same
request, which needs the per-transaction coalescing those receivers do. A graph
whose type changes to or from text or editorial also rebuilds the image's text
documents, which carry the coordinates of the regions a text links to.

Indexes whose document id is derived from the row rather than equal to its pk —
`clauses`, `people`, `places`, all `42_0`-style — cannot be addressed by pk, so
their registration names a `parent_id_field` and the sync clears them by filter
before rebuilding. That one delete waits for Meilisearch, unlike every other
incremental write: a filter naming an attribute the index has not been told to
filter on is accepted by the HTTP call and then fails inside Meilisearch's own
task queue, so without waiting it would delete nothing and say nothing.

## Progress reporting

`apps/search/progress.py` defines:

- `ProgressReporter` — `start(message)`,
  `advance_to(index_position, total_indexes, segment)`,
  `report_batch(done, total)`; every hook is a no-op, which is what the CLI
  and tests use when nobody is watching.
- `CeleryTaskReporter(task)` — wraps `task.update_state` so progress
  shows up on the management dashboard's task-status poll.

The contract is intentionally thin. `IndexingService` only knows
`report_batch`; `IndexingService.reindex_all`
adds `advance_to` between indexes; the Celery task primes the
reporter with `start`. None of these layers care which sink is
receiving — that's the reporter's job.

Don't thread callbacks down the layers to re-shape progress for the
next one. If you need a new transport (logs, websockets, a metrics
counter), write a new reporter class.

## Data flow: search

```
GET /api/v1/search/<segment>/?…           views_search.py
       │  (also …/facets/, …/export/, …/<pk>/, and /search/suggest/)
       ▼
   parsers.py: parse_search_query() → SearchQuery
       │  • structured filter params, sort, limit, offset
       │    (offset clamped to MAX_OFFSET = 1,000,000)
       │  • qb= base64url query-builder tree → qb_parser.py
       │  • parse_facet_attributes() — facet selections
       │
       ▼
   SearchService.search(IndexType, SearchQuery)    services.py
       │
       ▼
   MeilisearchIndexReader.search(...)              meilisearch/reader.py
       • meilisearch/filters.py builds the filter expression
       • returns SearchResult + optional FacetResult
```

`filter_contract.py` decides what reaches a filter expression, for both
the structured filters and the query-builder tree. `sanitize_filter_spec`
drops every attribute the index's registration does not list as
filterable — including the date range, which compiles to `date_min` /
`date_max` clauses and is ignored on indexes without those fields.
`escape_filter_value` quotes values, escaping backslashes and then double
quotes. Meilisearch rejects a whole search over one bad clause, and that
surfaces as a 500, so input it would refuse is dropped or clamped before
it gets there.

`SearchQuery`, `SearchResult`, `FilterSpec`, `FacetResult`, and
`SortSpec` are defined in `apps/search/types.py`. Anything that
crosses a layer boundary uses these — never raw dicts; the view turns
a `SearchResult` into the response body.

### Search contract

A few rules keep the response shape stable across the nine indexes; the
tests in `test_parsers.py`, `test_meilisearch_layer.py` and
`test_document_builders.py` pin them.

- **Sort aliases.** `IndexRegistration.sort_aliases` maps a public sort
  attribute to the attribute Meilisearch actually sorts on (`shelfmark` →
  `shelfmark_sort`, a natural-order key `documents/utils.py` derives so
  `MS 2` sorts before `MS 10`). The parser keeps the public name — it is
  what `ordering.current` and `/meta/` echo — and the reader swaps it in.
  The writer declares both (`index_sortable_attributes`).
- **`_formatted` is pruned.** The reader highlights only the index's
  searchable attributes, and `_formatted` is cut down to those plus
  whatever the query asked to crop. Everything else in a hit (the
  `coordinates` / `annotation_coordinates` JSON the result cards read, the
  numeric date bounds) comes back once, raw. Only the `texts` list crops
  `content` (`parsers._CROPPED_IN_LISTS`): a clause card shows its whole
  text, a text card a snippet.
- **One date triple.** `date` is a display string; `date_min` / `date_max`
  are the numeric bounds every dated index (`item-parts`, `item-images`,
  `hands`, the text indexes) filters, sorts and facets on. The date window
  parameters compile to them and are dropped on indexes without them.
- **`type` is always the historical-item type** (charter, letter, …) on
  every index that carries it. The text indexes keep the text's own kind in
  `text_type` (transcription, translation).
- **`catalogue_numbers` is a list** on every index (`["Ker 236", "Lawrie
  12"]`): one value per facet entry, each keeping its source.
- **`GET /search/<segment>/meta/`** returns the registration's searchable,
  filterable, sortable (public names) and default-facet attributes plus the
  export formats, so a client can build its controls without a search.
- **`…/export/?download=1`** serves the CSV, BibTeX or JSON itself with a
  `Content-Disposition` attachment; without it the text comes wrapped in
  JSON for the current frontend hook.
- **Query-builder comparisons.** `gte` / `lte` compile to `>=` / `<=`;
  `gt` / `lt` are accepted as the same thing until the frontend sends the
  new names.

## Document builders

One module per index in `apps/search/documents/`. Each exports a
`build_<thing>` callable that returns one document, a list of them, or
`None` to skip the row; `IndexRegistration.documents(obj)` normalises
that to a list.
Lists exist because some builders fan out (one `ImageText` produces N
clause documents, M place documents, etc.).

Cross-cutting parsers (one pass over a text's TEI — or legacy data-dpt —
markup) live in `apps/search/documents/dpt_parser.py` and are shared across the
`texts`, `clauses`, `places` and `people` builders. The parser is wrapped in
`functools.lru_cache` so the same `ImageText` parsed by four different
builders during a single rebuild only runs the state machine once per
worker. The cache is per process, so a parser change takes effect on
restart — but documents already in the index keep the old shape until the
affected indexes are reindexed.

`msdesc_parser.py` reads the item-parts facets that only exist in the
stored msDesc TEI (material, script, decoration, seal type and material,
origin place), and `utils.py` holds helpers the builders share.

## What lives where

| Concern | File |
|---|---|
| Index enumeration, models, row filters, attribute lists | `apps/search/registry.py` |
| Which indexes a model write invalidates | `apps/search/dependencies.py` |
| Signal receivers driving incremental sync | `apps/search/signals.py` |
| Public protocols (`SearchBackend`, `IndexDocumentBuilder`) | `apps/search/contracts.py` |
| DTOs (`SearchQuery`, `SearchResult`, `FilterSpec`, `FacetResult`, `SortSpec`) | `apps/search/types.py` |
| Celery tasks (single entry per operation) | `apps/search/tasks.py` |
| Application services (`SearchService`, `IndexingService`) | `apps/search/services.py` |
| Progress reporters | `apps/search/progress.py` |
| HTTP views | `apps/search/views_search.py`, `apps/search/views_management.py` (input serializer in `serializers.py`) |
| Export formats (CSV rows, BibTeX) | `apps/search/exports.py` |
| Filter / q-string parsers | `apps/search/parsers.py`, `apps/search/qb_parser.py` |
| Filter allow-list and value escaping | `apps/search/filter_contract.py` |
| Meilisearch reader / writer / client / filter builder | `apps/search/meilisearch/` |
| Per-index document builders | `apps/search/documents/<segment>.py` |
| Admin-side stats + actions | `apps/search/admin_service.py` |
| Data-quality dashboard probes | `apps/search/quality.py` |
| CLI (`setup_search_indexes`, `sync_search_index`, …) | `apps/search/management/commands/` |

`quality.py` also lives in this app (its view in `views_management.py`, mounted at
`/api/v1/search/management/quality/`) but is a superuser data-quality
dashboard over the database, not the search index: it is here only because
its cards span manuscripts, annotations and scribes, and `search` is the one
app the dependency graph lets import all three. The image-text monitoring
dashboard is in `apps/manuscripts` (`management/image-texts/overview/`); its
old `/api/v1/search/management/image-texts/overview/` path is kept as an alias
until the frontend moves.

## Adding a new index type

1. Add an `IndexType` member to `apps/search/types.py`.
2. Write a builder in `apps/search/documents/<segment>.py` and export it
   from the package `__init__`.
3. Add one `IndexRegistration` entry to `INDEX_REGISTRY` in
   `apps/search/registry.py`: the model, the
   filterable/sortable/searchable/facet attribute lists, the builder, the
   `select_related`/`prefetch_related` your builder needs, a
   `queryset_filter` or `queryset_exclude` if some rows are not public, and
   (for one-to-many indexes like clauses/people/places) `parent_id_field`
   plus a `documents_per_row` counter for the admin's in-sync check.
   That single entry **is** the whole registration —
   `get_queryset_for_index` applies the filters and prefetch spec generically.
4. If editing a model should keep the new index current, add an entry to
   `DEPENDENCIES` in `apps/search/dependencies.py` naming the indexes the
   write invalidates and how to find the rows to rebuild. Where one row
   produces several documents, set `parent_id_field` on the registration and
   include that field in both the builder and `filterable_attributes`, or the
   sync cannot remove them.
5. Run `just setup-search-indexes` against a dev Meilisearch to push
   the settings, then `just sync-search-index <segment>` to populate.
6. Add a builder test to `apps/search/tests/test_document_builders.py` and
   name it in that file's `BUILDER_COVERAGE` map; a meta-test there fails CI
   for any registered index without one.

There is no separate config file, no settings hook, no URL pattern to
edit. The registry is what makes the rest fall into place.

For day-to-day commands and incident response — including what to check
when database and index counts disagree — see
[`search-operations.md`](./search-operations.md).

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
  → writer adapter. Each layer has a single responsibility and a
  single test file.
- **Search**: HTTP request → DRF view → application service → reader
  adapter → Meilisearch. Filters and facets are parsed into typed
  `SearchQuery` objects so the backend never sees raw query strings.

## The registry is the single source of truth

`apps/search/registry.py` defines, for every index type:

- The `IndexType` enum value (e.g. `ITEM_PARTS`).
- Its URL segment (`item-parts`) — what the management API and CLI
  expect on the wire.
- The Django model it indexes (app label + model name).
- The **builder** callable that turns one ORM object into one or more
  documents (`apps/search/documents/<type>.py`).
- The filterable / sortable / searchable / facet attribute lists used
  when applying Meilisearch settings.

When you add a new index type, the registry is the file you edit
first. Everything else — tasks, views, the CLI's `--type` choices —
discovers the new entry through `INDEX_REGISTRY` and `IndexType`. The
test suite has a parametrised test that runs over `IndexType` so an
unregistered type fails CI rather than 404-ing in prod.

The registry also owns `get_queryset_for_index(index_type)`. Each index's
query optimization (`select_related` / `prefetch_related`) is declared
*on its `IndexRegistration` entry* and applied generically here — there is
no per-type branch. Builders trust the queryset is already shaped for their
access pattern; they don't add their own `select_related`.

## Data flow: indexing

```
                     ┌─ tasks.py (Celery entry point)
                     │  • reindex_search_index(segment)
                     │  • clear_search_index(segment)
                     │  • clean_and_reindex_search_index(segment)
                     │  • clear_and_reindex_all_search_indexes()
                     │
                     ▼
                 SearchOrchestrationService            services.py
                     │  • per-segment URL resolution
                     │  • outer multi-index loop for "all"
                     │
                     ▼
                 IndexingService.reindex(IndexType)    services.py
                     │  • iterates the registry queryset in batches
                     │  • atomic build-and-swap (see below)
                     │  • per-batch progress reports
                     │
                     ▼
                 MeilisearchIndexWriter                meilisearch/writer.py
                     • prepare_build_index, add_documents_to_build,
                       swap_with_build, drop_build_index, …
```

### Atomic build-and-swap (P1.3)

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
build index on its way through `prepare_build_index`.

This is the only place in the search stack with non-trivial recovery
semantics. Don't replace it with an "in-place delete-then-add" loop —
that pattern (which existed pre-P1.3) is the failure mode this is
designed to avoid.

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
              registration's queryset_filter applies
            • rows the queryset no longer returns are deleted
```

Two consequences worth knowing:

- **One call covers add, update and remove.** Because documents are rebuilt from
  a queryset rather than from a payload, a row that leaves the queryset — soft
  deleted, hard deleted, or excluded by `queryset_filter` — has its documents
  removed. That is what makes an `ImageText` moving between Draft and Live move
  its documents with it.
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
request, which needs the per-transaction coalescing those receivers do.

Indexes whose document id is derived from the row rather than equal to its pk —
`clauses`, `people`, `places`, all `42_0`-style — cannot be addressed by pk, so
their registration names a `parent_id_field` and the sync clears them by filter
before rebuilding. That one delete waits for Meilisearch, unlike every other
incremental write: a filter naming an attribute the index has not been told to
filter on is accepted by the HTTP call and then fails inside Meilisearch's own
task queue, so without waiting it would delete nothing and say nothing.

## Progress reporting (P3.12)

`apps/search/progress.py` defines:

- `ProgressReporter` (Protocol) — `start(message)`,
  `advance_to(index_position, total_indexes, segment)`,
  `report_batch(done, total)`.
- `NoopReporter` — default; used by the CLI and tests when nobody is
  watching.
- `CeleryTaskReporter(task)` — wraps `task.update_state` so progress
  shows up on the management dashboard's task-status poll.

The contract is intentionally thin. `IndexingService` only knows
`report_batch`; `SearchOrchestrationService.clear_and_reindex_all`
adds `advance_to` between indexes; the Celery task primes the
reporter with `start`. None of these layers care which sink is
receiving — that's the reporter's job.

Before this protocol existed, each layer wrapped the next layer's
callback in a closure that re-shaped the signature
((done, total) → (pos, total_indexes, segment, done, docs_total) →
`task.update_state`). Don't reintroduce that pattern. If you need a
new transport (logs, websockets, a metrics counter), write a new
reporter class.

## Data flow: search

```
GET /api/v1/search/<segment>/?…           views_search.py
       │
       ▼
   parsers.py: SearchQuery / FilterSpec construction
       │  • parse_filters() — Lucene-ish q-string → typed filters
       │  • parse_facets() — facet selections
       │
       ▼
   SearchService.search(IndexType, SearchQuery)    services.py
       │
       ▼
   MeilisearchIndexReader.search(...)              meilisearch/reader.py
       • builds the Meilisearch filter expression
       • returns SearchResult + optional FacetResult
```

`SearchQuery`, `SearchResult`, `FilterSpec`, `FacetResult`, and
`SortSpec` are defined in `apps/search/types.py`. Anything that
crosses a layer boundary uses these — never raw dicts. The DRF
serializers in `apps/search/serializers.py` only handle the
HTTP-shape ↔ `SearchResult` conversion.

## Document builders

One module per index in `apps/search/documents/`. Each module exports
a single callable `build_<thing>(obj) -> Iterable[SearchDocument]`.
"Iterable" because some builders fan out (one `ImageText` produces N
clause documents, M place documents, etc.).

Cross-cutting parsers (the data-dpt HTML state machine) live in
`apps/search/documents/dpt_parser.py` and are shared across the
`clauses`, `places`, `people` builders. The parser is wrapped in
`functools.lru_cache` keyed by `(html_content, PARSER_VERSION)` so
the same `ImageText` parsed by four different builders during a
single rebuild only runs the state machine once per worker (P3.11).
Bump `PARSER_VERSION` whenever you change the parser's behaviour; the
cache invalidates automatically.

## What lives where

| Concern | File |
|---|---|
| Index enumeration, models, attribute lists | `apps/search/registry.py` |
| Which indexes a model write invalidates | `apps/search/dependencies.py` |
| Signal receivers driving incremental sync | `apps/search/signals.py` |
| Public protocols (`SearchBackend`, `IndexDocumentBuilder`) | `apps/search/contracts.py` |
| DTOs (`SearchQuery`, `SearchResult`, `FilterSpec`, `FacetResult`) | `apps/search/types.py` |
| Celery tasks (single entry per operation) | `apps/search/tasks.py` |
| Application services (orchestration + indexing) | `apps/search/services.py` |
| Progress reporters | `apps/search/progress.py` |
| HTTP views | `apps/search/views_search.py`, `apps/search/views_admin.py` |
| Filter / q-string parsers | `apps/search/parsers.py`, `apps/search/qb_parser.py` |
| Meilisearch reader / writer / client | `apps/search/meilisearch/` |
| Per-index document builders | `apps/search/documents/<segment>.py` |
| Admin-side stats + actions | `apps/search/admin_service.py` |

## Adding a new index type

1. Add an `IndexType` member to `apps/search/types.py`.
2. Write a builder in `apps/search/documents/<segment>.py` returning
   `Iterable[SearchDocument]` (the `__init__` `normalize_builder` wraps
   single-dict builders into the iterable form).
3. Add one `IndexRegistration` entry to `INDEX_REGISTRY` in
   `apps/search/registry.py`: model label, the
   filterable/sortable/searchable/facet attribute lists, the builder,
   the `select_related`/`prefetch_related` your builder needs, and (for
   one-to-many indexes like clauses/people/places) a `count_extractor`.
   That single entry **is** the whole registration — the URL segment is
   derived from the enum, and `get_queryset_for_index` applies the
   prefetch spec generically. (Before, this data was split across an
   enum, four parallel dicts in a separate `index_metadata.py`, a
   `MODEL_LABELS` map, a builders map, and a `_optimize_queryset` ladder;
   it now lives in this one table.)
4. If editing a model should keep the new index current, add an entry to
   `DEPENDENCIES` in `apps/search/dependencies.py` naming the indexes the
   write invalidates and how to find the rows to rebuild. Where one row
   produces several documents, set `parent_id_field` on the registration and
   include that field in both the builder and `filterable_attributes`, or the
   sync cannot remove them.
5. Run `just setup-search-indexes` against a dev Meilisearch to push
   the settings, then `just sync-search-index <segment>` to populate.
6. Add a builder test under `apps/search/tests/test_document_builders.py`
   and a registry contract test (the parametrised one).

There is no separate config file, no settings hook, no URL pattern to
edit. The registry is what makes the rest fall into place.

## Operational pointers

- **Live state vs DB state**: `SearchAdminService.get_index_stats_list`
  compares `db_count` (`get_queryset_for_index(...).count()` modulo the
  one-to-many extractors) against Meilisearch's reported document
  count. A persistent mismatch usually means: builder crash on some
  row, a stale `__build` index, or a Meilisearch downgrade losing
  documents. Investigate in that order.
- **Reindex tasks are idempotent**: retrying after a failure is safe.
  The build-and-swap pattern guarantees nothing observable changes
  until the swap succeeds.
- **`PARSER_VERSION` bumps need a reindex**: caches invalidate
  per-process, but already-indexed documents have the *old* shape.
  Bump → reindex affected types → bump cleared.

For day-to-day commands and incident response, see
[`search-operations.md`](./search-operations.md).

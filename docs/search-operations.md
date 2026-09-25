# Search Operations Runbook

This runbook covers day-to-day search index operations for the backend.

## Prerequisites

- Services are running via Docker Compose.
- `api`, `celery`, `redis`, and `meilisearch` are healthy.

## Health checks

- API search stats endpoint: `GET /api/v1/search/management/stats/` (superuser).
- Container-level checks:
  - `docker compose ps`
  - `docker compose logs -f celery`
  - `docker compose logs -f meilisearch`

## Index setup and synchronization

- Initialize all indexes:
  - `just setup-search-indexes`
- Reindex a single index:
  - `just sync-search-index item-parts`
  - Other valid values: `item-images`, `scribes`, `hands`, `graphs`, `texts`, `clauses`, `people`, `places`
- Reindex all indexes:
  - `just sync-all-search-indexes`

## After changing a document shape or index settings

Deploys that change a document builder (`apps/search/documents/*`) or the
registry attribute lists (`apps/search/registry.py`) do **not** rebuild
existing documents — there is no deploy hook and no model-save signal for
these indexes. Once **both** the `api` and `celery` containers run the new
image, reindex each affected index:

- `just sync-search-index <index>` (or the management API `reindex` action)

This release is one of those changes. `clauses`, `people` and `places` gained an
`image_text` field that their filtered deletes match on, so reindex those three
once after deploying. Until you do, every sync of a text will fail with
`invalid_document_filter` rather than quietly leaving orphans behind.

A sync applies the new index settings *and* rebuilds the documents;
`just setup-search-indexes` alone only applies settings and leaves stale
documents in place. Do not trigger the reindex while `celery` still runs the
old image — the management API dispatches to the worker, so an old worker
rebuilds documents with the old builder.

## Management API actions

All actions below require a superuser-authenticated API client.

- Reindex one index:
  - `POST /api/v1/search/management/actions/`
  - Body: `{"action":"reindex","index_type":"item-parts"}`
- Clear one index:
  - Body: `{"action":"clear","index_type":"item-parts"}`
- Clear and reindex one index:
  - Body: `{"action":"clean_and_reindex","index_type":"item-parts"}`
- Reindex all:
  - Body: `{"action":"reindex_all"}`
- Clear and rebuild all:
  - Body: `{"action":"clear_and_rebuild_all"}`

Track task execution with:

- `GET /api/v1/search/management/tasks/<task_id>/`

### Command-line operations

Use compose-backed commands through just recipes:

- `just setup-search-indexes`
- `just sync-search-index item-parts`
- `just sync-all-search-indexes`

These commands now share index-resolution and orchestration behavior with management APIs via `SearchOrchestrationService`.

## Incident response

### Symptom: Search results are stale

Editor writes sync themselves, so this is a fault rather than routine
maintenance. Work out which link broke before reaching for a rebuild:

1. Confirm DB and index counts from the stats endpoint (or **Backoffice → Search
   Engine**, which shows the same `in_sync` comparison per index). Note that it
   compares counts only — an index with the right number of stale documents
   still reads as in sync.
2. Check `SEARCH_AUTO_REINDEX` is not `false` on **both** `api` and `celery`.
   It is the documented kill switch, so a leftover `false` from a bulk operation
   is the most common cause.
3. Check the Celery worker is running and draining. A write enqueues
   `sync_search_documents` on commit; if the broker was unreachable at that
   moment, that one update is lost and only a reindex recovers it.
4. If a document builder or the registry attribute lists changed in the last
   deploy, see "After changing a document shape or index settings" above —
   those are not rebuilt automatically.
5. Only then trigger `clean_and_rebuild_all` from the management API, monitor
   Celery task states until success, and re-run representative queries and
   facet requests.

### Symptom: Sync queue is overloaded

A write fans out to every index whose documents copy the edited row's values, in
chunks of 500 source rows. Most edits are a handful of tasks. A rename on a
repository or a heavily annotated scribe is many more, and takes longer to
drain. That is expected.

1. Check the Celery worker log for the shape of the backlog: `sync_search_documents`
   tasks draining steadily is normal, repeated retries are not.
2. `SEARCH_AUTO_REINDEX=false` on **both** `api` and `celery` stops *new* writes
   from queueing anything. It does **not** drain what is already queued — the
   tasks themselves do not consult it — so an in-flight backlog also needs the
   Celery queue purging.
3. Run a controlled reindex once writes have settled, and turn the switch back on.

### Symptom: Is incremental sync still working?

Nothing reports this on its own — the stats endpoint compares document *counts*,
so a field that synced wrongly still reads as in sync. The cheap check is the
worker log: edit something in the backoffice and confirm a `sync_search_documents`
task appears for it. Silence means the receivers are not firing (check
`SEARCH_AUTO_REINDEX`) or the broker is unreachable.

### Symptom: Management action rejected as unknown

1. Confirm `index_type` uses URL segment values (`item-parts`, `item-images`, `scribes`, `hands`, `graphs`, `texts`, `clauses`, `people`, `places`).
2. Retry using `/api/v1/search/management/actions/`.
3. If still failing, run `just sync-all-search-indexes` and review `api`/`celery` logs.

### Symptom: Meilisearch unavailable

1. Check `meilisearch` container health/logs.
2. Verify `MEILISEARCH_URL` and `MEILISEARCH_API_KEY`.
3. Restore service, then run `just sync-all-search-indexes`.

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

1. Confirm DB and index counts from stats endpoint.
2. Trigger `clean_and_rebuild_all` from management API.
3. Monitor Celery task states until success.
4. Re-run representative queries and facet requests.

### Symptom: Reindex queue is overloaded

1. Check Celery worker logs for repeated index tasks.
2. Confirm debounce behavior is enabled:
   - `SEARCH_AUTO_REINDEX=true`
   - `SEARCH_REINDEX_DEBOUNCE_SECONDS` set to a positive value.
3. Temporarily disable auto reindex by env (`SEARCH_AUTO_REINDEX=false`) if needed.
4. Run a controlled manual reindex after writes settle.

### Symptom: Management action rejected as unknown

1. Confirm `index_type` uses URL segment values (`item-parts`, `item-images`, `scribes`, `hands`, `graphs`, `texts`, `clauses`, `people`, `places`).
2. Retry using `/api/v1/search/management/actions/`.
3. If still failing, run `just sync-all-search-indexes` and review `api`/`celery` logs.

### Symptom: Meilisearch unavailable

1. Check `meilisearch` container health/logs.
2. Verify `MEILISEARCH_URL` and `MEILISEARCH_API_KEY`.
3. Restore service, then run `just sync-all-search-indexes`.

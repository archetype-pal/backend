# Search Operations Runbook

This runbook covers day-to-day search index operations for the backend. How
the pieces fit together is in [`search-architecture.md`](./search-architecture.md).

## Prerequisites

- Services are running via Docker Compose.
- `api`, `celery`, `redis`, and `meilisearch` are healthy.
- The `just` recipes below are this repo's, for the local stack. On a deployment,
  run the same-named recipes from the infrastructure repo, which adds
  `just reindex` (setup + sync all).

## Health checks

- API search stats endpoint: `GET /api/v1/search/management/stats/` (superuser).
- Container-level checks:
  - `docker compose --env-file config/.env ps`
  - `docker compose --env-file config/.env logs -f celery`
  - `docker compose --env-file config/.env logs -f meilisearch`

## Index setup and synchronization

- Create every index and apply its settings (no documents):
  - `just setup-search-indexes`
- Reindex a single index:
  - `just sync-search-index item-parts`
  - Other valid values: `item-images`, `scribes`, `hands`, `graphs`, `texts`, `clauses`, `people`, `places`
- Reindex all indexes (creates any that are missing):
  - `just sync-all-search-indexes`

These run the rebuild synchronously in a one-off `api` container, not on the
Celery worker, through the same `IndexingService` as the management API.

## After changing a document shape or index settings

Deploys that change a document builder (`apps/search/documents/*`) or the
registry attribute lists or row filters (`apps/search/registry.py`) do **not**
rebuild existing documents. No deploy step reindexes, and incremental sync only
rebuilds the rows that are written. Once **both** the `api` and `celery`
containers run the new image, reindex each affected index:

- `just sync-search-index <index>` (or the management API `reindex` action)

A sync applies the new index settings *and* rebuilds the documents;
`just setup-search-indexes` alone only applies settings and leaves stale
documents in place. It is idempotent and takes seconds, so run it in the
post-deploy step next to `migrate`: a facet added to the registry then never
400s (the search service degrades to "no facets" until the settings land, but
silently). Do not trigger the reindex while `celery` still runs the
old image — the management API dispatches to the worker, so an old worker
rebuilds documents with the old builder.

Document-shape changes that need a full reindex after deploy (most recent
first):

- `shelfmark_sort` on every manuscript-bearing index, `date_min` / `date_max`
  on `hands` and `item-images`, `catalogue_numbers` as a list on
  `item-parts`, `hands`, `texts` and `clauses`: `just reindex` (all indexes)
  once both containers run the new image. Until then sorting by shelfmark
  falls back to Meilisearch's order for documents without the key.

## Management API actions

All actions below require a superuser-authenticated API client.

- Reindex one index:
  - `POST /api/v1/search/management/actions/`
  - Body: `{"action":"reindex","index_type":"item-parts"}`
- Clear one index (deletes its documents; search returns nothing until a reindex):
  - Body: `{"action":"clear","index_type":"item-parts"}`
- Reindex all (one task per index):
  - Body: `{"action":"reindex_all"}`
- Reindex all in one task (index by index, with progress):
  - Body: `{"action":"clear_and_rebuild_all"}`

`clean_and_reindex` (per index) and `clear_and_rebuild_all` are accepted for
existing clients but are plain reindexes: every rebuild goes into a staging
index and is swapped in, so search keeps serving the old documents until the
swap. Nothing empties the live index except an explicit `clear`.

A second rebuild of an index that is already rebuilding fails with
`A reindex for '<index>' is already running.` Wait for the first one; the lock
expires on its own after an hour if a worker died holding it.

Track task execution with:

- `GET /api/v1/search/management/tasks/<task_id>/`

## Incident response

### Symptom: Search results are stale

Editor writes sync themselves, so this is a fault rather than routine
maintenance. Work out which link broke before reaching for a rebuild:

1. Confirm DB and index counts from the stats endpoint (or **Backoffice →
   Indexing**, `/backoffice/search-engine`, which shows the same `in_sync`
   comparison per index). Note that it compares counts only — an index with the
   right number of stale documents still reads as in sync. A persistent
   mismatch usually means a builder crashing on some row, a stale `__build`
   index, or a Meilisearch downgrade losing documents; investigate in that
   order.
2. Check `SEARCH_AUTO_REINDEX` is not `false` on **both** `api` and `celery`.
   It is the documented kill switch, so a leftover `false` from a bulk operation
   is the most common cause.
3. Check the Celery worker is running and draining. A write enqueues
   `sync_search_documents` on commit; if the broker was unreachable at that
   moment the write still succeeds, an ERROR is logged (and mailed to ADMINS)
   naming the index, and only a reindex recovers that update. A document
   Meilisearch itself rejects fails the sync task with Meilisearch's error
   code, visible in the worker log.
4. If a document builder or the registry attribute lists changed in the last
   deploy, see "After changing a document shape or index settings" above —
   those are not rebuilt automatically.
5. Only then trigger `clear_and_rebuild_all` from the management API, monitor
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

### Symptom: Management action rejected

The 400 response's `detail` names the problem:

1. Unknown action — valid ones are `reindex`, `clear`, `clean_and_reindex`,
   `reindex_all`, `clear_and_rebuild_all`.
2. `'index_type' is required` — the three per-index actions need one.
3. Unknown index type — `index_type` takes URL segment values (`item-parts`,
   `item-images`, `scribes`, `hands`, `graphs`, `texts`, `clauses`, `people`,
   `places`), not the underscored enum values.

### Symptom: Meilisearch unavailable

1. Check `meilisearch` container health/logs. The stats endpoint reports
   `"healthy": false`.
2. Verify `MEILISEARCH_URL` and `MEILISEARCH_API_KEY` (in a deployment the key
   must match `MEILI_MASTER_KEY`).
3. Restore service, then run `just sync-all-search-indexes`. Incremental syncs
   retry a few times and then give up, so writes made during the outage are
   missing until you do.

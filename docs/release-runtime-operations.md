# Release and Runtime Operations

This runbook captures release promotion checks and runtime troubleshooting for the backend service.

## Release flow

1. Ensure CI is green on the commit you plan to release.
2. Trigger `cd.yml` to build and publish:
   - `ghcr.io/archetype-pal/backend:latest`
   - `ghcr.io/archetype-pal/backend:sha-<commit>`
3. Verify image startup smoke test passes in workflow logs.
4. Trigger `cd-staging.yml` with `source_tag=sha-<commit>` to promote an immutable image to `:staging`.
5. Confirm `:staging` tag inspect step succeeds.

## Rollback guidance

- Keep a known-good `sha-<commit>` tag available before promoting.
- To roll back staging, rerun `cd-staging.yml` with the previous known-good `source_tag`.

## Runtime checks

- Confirm containers are healthy:
  - `docker compose ps`
- Check API container logs:
  - `docker compose logs api --tail=200`
- Check Celery worker logs:
  - `docker compose logs celery --tail=200`
- Check search backend logs:
  - `docker compose logs meilisearch --tail=200`

## Search incident shortcuts

- Recreate index settings:
  - `make setup-search-indexes`
- Reindex one index:
  - `make sync-search-index INDEX=item-parts`
- Reindex all indexes:
  - `make sync-all-search-indexes`

See `docs/search-operations.md` for detailed search troubleshooting and management endpoint usage.

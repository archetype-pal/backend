# PostgreSQL 18 Upgrade

The local Docker Compose stack now runs PostgreSQL 18 via `postgres:18.3-bookworm`.

PostgreSQL major versions cannot reuse an older major version data directory in place. The PostgreSQL 18 Docker image also changed its default data layout: `PGDATA` is version-specific (`/var/lib/postgresql/18/docker`) and volumes should mount `/var/lib/postgresql`, not `/var/lib/postgresql/data`.

Primary references:

- PostgreSQL 18 `pg_upgrade`: https://www.postgresql.org/docs/18/pgupgrade.html
- PostgreSQL cluster upgrade strategies: https://www.postgresql.org/docs/current/upgrading.html
- Docker official `postgres` image `PGDATA` notes: https://hub.docker.com/_/postgres/

## What Changed

- `compose.yaml` uses `POSTGRES_IMAGE`, defaulting to `postgres:18.3-bookworm`.
- The PostgreSQL 18 service writes to the `postgres18` named volume.
- `PGDATA` is explicit: `/var/lib/postgresql/18/docker`.
- The old local PostgreSQL 17 Docker volume, usually `archetype_postgres`, is not used by the PostgreSQL 18 compose service.

This keeps old local data separate from the new PostgreSQL 18 volume. If the migration fails, the old PostgreSQL 17 volume is still available by Docker volume name.

## Fresh Local Setup

For a new local database, no upgrade is needed:

```bash
docker compose up -d postgres
just migrate
just postgres-version
```

`just postgres-version` should report PostgreSQL 18.x.

## Existing Local PostgreSQL 17 Volume

If you already have local data in the old `archetype_postgres` Docker volume, run:

```bash
just postgres-upgrade-17-to-18
```

The helper:

1. Stops local compose services that could write to the database.
2. Starts a temporary PostgreSQL 17 container against the old `archetype_postgres` volume.
3. Creates logical custom-format dumps of every non-template database except the maintenance `postgres` database. On this local development machine that included `local`, `test_db`, and the legacy `old_arch` database; other environments may have different database names.
4. Starts the PostgreSQL 18 compose service on the new `archetype_postgres18` volume.
5. Restores the dump into PostgreSQL 18.
6. Runs `vacuumdb --all --analyze-in-stages`.
7. Runs Django migrations unless `--skip-migrate` is passed.

Backups are written under `backups/postgres-upgrade/<timestamp>/`.

Use `--yes` for non-interactive local runs:

```bash
./scripts/upgrade-postgres-17-to-18-local.sh --yes
```

To force a specific local database, set `POSTGRES_DB`:

```bash
POSTGRES_DB=local ./scripts/upgrade-postgres-17-to-18-local.sh --yes
```

To force an explicit set, first confirm the database names in that environment:

```bash
POSTGRES_DATABASES=local,test_db,old_arch ./scripts/upgrade-postgres-17-to-18-local.sh --yes
```

If you need to retry and the PostgreSQL 18 volume is already initialized, inspect it first. The helper intentionally refuses to overwrite an initialized `archetype_postgres18` volume.

## Local Verification

After migration:

```bash
just postgres-version
docker compose run --rm api python manage.py check
just migrate
just pytest-focused
```

If you depend on Meilisearch data while testing locally, rebuild indexes after verifying the database:

```bash
just setup-search-indexes
just sync-all-search-indexes
```

## Server Upgrade Runbook

Use this as the server handoff checklist when the pushed compose change is deployed.

1. Schedule a maintenance window.
2. Confirm the current PostgreSQL major version, data location, and database names. Do not assume the server has the same `local`, `test_db`, or `old_arch` databases as a development machine.
3. Take two backups before changing the runtime:
   - provider or filesystem snapshot of the current database volume
   - logical dump with `pg_dump` or `pg_dumpall`, stored off-host
4. Stop API, Celery, scheduled jobs, and any process that writes to PostgreSQL.
5. Upgrade with one of these strategies:
   - managed database: use the provider's PostgreSQL 18 major-version upgrade path
   - Docker volume: perform a dump/restore into a fresh PostgreSQL 18 volume
   - larger self-hosted database: use `pg_upgrade` after rehearsing it on a copy of production data
6. Start PostgreSQL 18 only after the new data directory or restored volume is ready.
7. Run Django migrations.
8. Run smoke tests against the API and admin flows.
9. Run `vacuumdb --all --analyze-in-stages` if the upgrade path did not already analyze the restored database.
10. Rebuild Meilisearch indexes if search results drift or if the deployment process recreated Meilisearch data.

Rollback rule: never start PostgreSQL 17 on a PostgreSQL 18 data directory. Roll back by restoring the PostgreSQL 17 snapshot/dump and pointing the runtime back at the old PostgreSQL 17 volume/image.

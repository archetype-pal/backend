# PostgreSQL 18 Upgrade (local dev stack)

The dev stack in `compose.yaml` runs PostgreSQL 18 (`POSTGRES_IMAGE`, default set in `compose.yaml`). This page covers moving a **local** PostgreSQL 17 volume onto it. Servers use the infrastructure stack and its own helper: see [`infrastructure/docs/postgresql-18-upgrade.md`](https://github.com/archetype-pal/infrastructure/blob/main/docs/postgresql-18-upgrade.md).

PostgreSQL major versions cannot reuse an older major version's data directory in place. The PostgreSQL 18 image also changed its data layout: `PGDATA` is version-specific (`/var/lib/postgresql/18/docker`, set in `config/.env`), and the `postgres18` volume mounts `/var/lib/postgresql`, not `/var/lib/postgresql/data`. The old PostgreSQL 17 volume, `archetype_postgres`, is left untouched, so it stays available if the migration fails.

## Fresh Local Setup

A new local database needs no upgrade:

```bash
just up-bg
just migrate
just postgres-version
```

`just postgres-version` should report PostgreSQL 18.x.

## Existing Local PostgreSQL 17 Volume

If you have local data in the old `archetype_postgres` Docker volume, run:

```bash
just postgres-upgrade-17-to-18
```

The helper (`scripts/upgrade-postgres-17-to-18-local.sh`, which needs `config/.env`):

1. Stops local compose services that could write to the database.
2. Starts a temporary PostgreSQL 17 container against the old `archetype_postgres` volume.
3. Creates custom-format dumps of every non-template database except the maintenance `postgres` database.
4. Starts the PostgreSQL 18 compose service on the new `archetype-dev_postgres18` volume.
5. Restores the dumps into PostgreSQL 18.
6. Runs `vacuumdb --all --analyze-in-stages`.
7. Runs Django migrations unless `--skip-migrate` is passed.

Backups are written under `backups/postgres-upgrade/<timestamp>/`.

Use `--yes` for non-interactive runs, and `POSTGRES_DB` or `POSTGRES_DATABASES` to choose the databases:

```bash
./scripts/upgrade-postgres-17-to-18-local.sh --yes
POSTGRES_DB=local ./scripts/upgrade-postgres-17-to-18-local.sh --yes
POSTGRES_DATABASES=local,test_db ./scripts/upgrade-postgres-17-to-18-local.sh --yes
```

If you need to retry and the PostgreSQL 18 volume is already initialized, inspect it first. The helper refuses to overwrite an initialized `archetype-dev_postgres18` volume.

## Local Verification

After migration:

```bash
just postgres-version
docker compose --env-file config/.env run --rm api python manage.py check
just migrate
just pytest-focused
```

If you depend on Meilisearch data while testing locally, rebuild indexes after verifying the database:

```bash
just setup-search-indexes
just sync-all-search-indexes
```

Never start PostgreSQL 17 on a PostgreSQL 18 data directory.

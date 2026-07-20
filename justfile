set export

_default:
    @just --list

build:
    docker compose build

up:
    docker compose up

down:
    docker compose down --remove-orphans

# bg stands for background
up-bg:
    docker compose up -d

makemigrations:
    docker compose run --rm api python manage.py makemigrations

postgres-version:
    docker compose exec -T postgres bash -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW server_version;"'

# Dump the local DB to a timestamped plain-SQL file under backups/ (gitignored via *.sql).
postgres-dump:
    mkdir -p backups
    docker compose exec -T postgres bash -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "backups/$(date +%Y%m%d-%H%M%S).sql"

# Destructive: atomically overwrite the local DB from FILE, then resync sequences.
postgres-restore FILE: && sync-sequences
    docker compose exec -T postgres bash -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;" -f -' < "$FILE"

postgres-upgrade-17-to-18:
    ./scripts/upgrade-postgres-17-to-18-local.sh

# Resync every postgres sequence in the public schema to MAX(id) of its owning
# column. Idempotent. Fixes UniqueViolation after explicit-id imports/restores
# when a sequence drifts below MAX(id). Handles both serial and identity
# sequences.
sync-sequences:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose run --rm api python - <<'PY'
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django
    from django.db import connection

    django.setup()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            DO $$
            DECLARE r record; mv bigint; has_rows boolean;
            BEGIN
              FOR r IN
                SELECT n.nspname AS schema_name, c.relname AS seq, t.relname AS tbl, a.attname AS col
                FROM pg_class c
                JOIN pg_depend d ON d.objid = c.oid AND d.deptype IN ('a', 'i')
                JOIN pg_class t ON d.refobjid = t.oid
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'S' AND n.nspname = 'public'
              LOOP
                EXECUTE format(
                  'SELECT COALESCE(MAX(%I), 1), MAX(%I) IS NOT NULL FROM %I.%I',
                  r.col, r.col, r.schema_name, r.tbl
                ) INTO mv, has_rows;
                PERFORM setval(format('%I.%I', r.schema_name, r.seq)::regclass, mv, has_rows);
              END LOOP;
            END $$;
            """
        )
    print(f"Synchronized public id sequences for database {connection.settings_dict['NAME']}.")
    PY

migrate: sync-sequences
    docker compose run --rm api python manage.py migrate

restart-api:
    docker compose restart api

pytest:
    docker compose --env-file config/test.env run --rm api python -m pytest

pytest-focused:
    mkdir -p .test-results && chmod 777 .test-results
    docker compose --env-file config/test.env run --rm -e USE_SQLITE_FOR_TESTS=1 api python -m pytest apps/annotations/tests/tests.py apps/search/tests/test_services.py -q --junitxml=/app/.test-results/junit-focused.xml

pytest-search:
    docker compose --env-file config/test.env run --rm api python -m pytest apps/search/tests/ -v

coverage:
    mkdir -p .test-results && chmod 777 .test-results
    docker compose --env-file config/test.env run --rm -e COVERAGE_FILE=/tmp/.coverage api python -m pytest --cov=apps --cov=config --cov-report=term-missing --cov-report=xml:/app/.test-results/coverage.xml --cov-fail-under=55 --junitxml=/app/.test-results/junit.xml

shell:
    docker compose run --rm api python manage.py shell_plus

bash:
    docker compose run --rm api bash

# Meilisearch: create indexes and sync from DB (run after first deploy or when index_not_found)
setup-search-indexes:
    docker compose run --rm api python manage.py setup_search_indexes

sync-search-index INDEX:
    docker compose run --rm api python manage.py sync_search_index {{INDEX}}

sync-all-search-indexes:
    docker compose run --rm api python manage.py sync_all_search_indexes

clean:
    uvx ruff check --fix .

check-architecture:
    uv run python scripts/check_architecture_boundaries.py

celery_status:
    docker compose run --rm api celery -A config inspect active

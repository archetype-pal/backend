set export

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

# Resync every postgres sequence in the public schema to MAX(id) of its owning
# column. Idempotent. Fixes UniqueViolation in Django's post-migrate signal
# when a sequence drifts below MAX(id) after a pg_dump restore.
sync-sequences:
    #!/usr/bin/env bash
    set -euo pipefail
    docker compose exec -T postgres bash -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q' <<'SQL'
    DO $$
    DECLARE r record; mv bigint;
    BEGIN
      FOR r IN
        SELECT n.nspname AS schema, c.relname AS seq, t.relname AS tbl, a.attname AS col
        FROM pg_class c
        JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'a'
        JOIN pg_class t ON d.refobjid = t.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'S' AND n.nspname = 'public'
      LOOP
        EXECUTE format('SELECT COALESCE(MAX(%I), 0) FROM %I.%I', r.col, r.schema, r.tbl) INTO mv;
        EXECUTE format('SELECT setval(%L, %s)', r.schema || '.' || r.seq, GREATEST(mv, 1));
      END LOOP;
    END $$;
    SQL

migrate: sync-sequences
    docker compose run --rm api python manage.py migrate

restart-api:
    docker compose restart api

pytest:
    API_ENV_FILE=config/test.env docker compose run --rm api python -m pytest

pytest-focused:
    mkdir -p .test-results && chmod 777 .test-results
    API_ENV_FILE=config/test.env docker compose run --rm -e USE_SQLITE_FOR_TESTS=1 api python -m pytest apps/annotations/tests/tests.py apps/search/tests/test_services.py -q --junitxml=/app/.test-results/junit-focused.xml

pytest-search:
    API_ENV_FILE=config/test.env docker compose run --rm api python -m pytest apps/search/tests/ -v

coverage:
    mkdir -p .test-results && chmod 777 .test-results
    API_ENV_FILE=config/test.env docker compose run --rm -e COVERAGE_FILE=/tmp/.coverage api python -m pytest --cov=apps --cov=config --cov-report=term-missing --cov-report=xml:/app/.test-results/coverage.xml --cov-fail-under=55 --junitxml=/app/.test-results/junit.xml

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

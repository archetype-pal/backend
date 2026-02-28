# Archetype

Backend APIs and services for the Archetype stack — revamped successor to [DigiPal](https://github.com/kcl-ddh/digipal).

See [CONTRIBUTING.md](CONTRIBUTING.md) before contributing.

## Stack

- **Database:** Postgres
- **Search:** Meilisearch
- **IIIF:** [SIPI](https://github.com/dasch-swiss/sipi)
- **API:** Django / Django REST Framework (Python 3.14, UV, Docker Compose)

API docs: `/api/v1/docs`

---

## Quick start

1. Copy env: `config/test.env` → `config/.env`
2. Start services: `docker compose up` (or `make up-bg` for background)
3. First run: `make migrate`

Use the [Makefile](Makefile) for migrate, pytest, shell, search index setup, and more.
### Testing

- Fast focused tests (compose-backed): `docker compose run --rm -e USE_SQLITE_FOR_TESTS=1 -e DJANGO_ENV=test api python -m pytest apps/annotations/tests/tests.py apps/search/tests/test_services.py -q`
- Full coverage gate: `make coverage`
- Search-only tests: `make pytest-search`

## Deploy

Image: [GitHub Packages](https://github.com/archetype-pal/archetype3/pkgs/container/archetype3). For simple setups, use `compose.yaml` on your server.

### Production checklist

Before running in production, ensure:

- **SECRET_KEY** — Set a strong random value; never use the default or values from `config/test.env`.
- **DEBUG** — Set to `false`.
- **ALLOWED_HOSTS** — Set to your domain(s), e.g. `yourdomain.com,api.yourdomain.com`.
- **DATABASE_URL** — Production Postgres URL (user, password, host, port, dbname).
- **CORS_ALLOWED_ORIGINS** / **CSRF_TRUSTED_ORIGINS** — Your frontend/origin URLs.
- **CELERY_BROKER_URL** / **CELERY_RESULT_BACKEND** — Redis (or other broker) URL if using Celery.
- **MEILISEARCH_API_KEY** — Set when Meilisearch is run with master key (recommended in production).

## Search operations

Operational guidance for indexing, health checks, and incident recovery lives in [`docs/search-operations.md`](docs/search-operations.md).

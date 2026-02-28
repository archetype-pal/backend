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

1. Copy env: `config/test.env` -> `config/.env`
2. Start services: `docker compose up` (or `make up-bg` for background)
3. First run: `make migrate`

Use the [Makefile](Makefile) for migrate, pytest, shell, search index setup, and more.
### Testing

- Fast focused tests (compose-backed): `make pytest-focused`
- Full coverage gate: `make coverage`
- Search-only tests: `make pytest-search`

### Runtime environment contract

- Compose is the canonical runtime for local development and CI.
- `config/test.env` is the baseline env contract used by compose-backed tests.
- Runtime behavior is driven entirely by env values in your active env file.
- `DEBUG=false` enables strict startup checks (`SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`) and secure cookie/HSTS defaults.

## Architecture guardrails

- API views stay transport-focused (validation, HTTP mapping, response shape).
- Application services own orchestration and task dispatch.
- Domain services own mutation workflows (serializers should not embed write orchestration).
- Search index metadata is registry-driven (`apps/search/registry.py`) to keep index additions predictable.

## Deploy

Image: [GitHub Packages](https://github.com/orgs/archetype-pal/packages/container/package/backend). For simple setups, use `compose.yaml` on your server.

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
Single-index sync uses URL segments from the search registry (for example: `item-parts`, `item-images`, `scribes`, `hands`, `graphs`, `texts`, `clauses`, `people`, `places`).

## Release and runtime operations

Release/staging verification and runtime incident guidance lives in [`docs/release-runtime-operations.md`](docs/release-runtime-operations.md).

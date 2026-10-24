# Archetype

Backend APIs and services for the Archetype stack — revamped successor to [DigiPal](https://github.com/kcl-ddh/digipal).

See [CONTRIBUTING.md](CONTRIBUTING.md) before contributing: workflow, the checks CI runs, code guardrails and releases. Coding agents also read [AGENTS.md](AGENTS.md).

## Stack

- **Database:** PostgreSQL 18
- **Search:** Meilisearch
- **IIIF:** [SIPI](https://github.com/dasch-swiss/sipi)
- **API:** Django 6.1 / Django REST Framework, Celery (Python 3.15, uv, Docker Compose)

API docs: `/api/v1/docs/` (Swagger UI), schema at `/api/v1/schema/`.

---

## Quick start

The backend runs in Docker Compose. Use the [justfile](justfile) recipes; `just` lists them all.

1. Copy env: `cp config/test.env config/.env`
2. Start services: `just up` (or `just up-bg` for background)
3. First run: `just migrate`, then `just sync-all-search-indexes` to create and fill the search indexes

The API is then on `http://localhost:8000`. Calling `docker compose` directly needs `--env-file config/.env`; the recipes pass it for you.

Works on Linux, macOS (Apple Silicon included — every image is multi-arch),
and Windows. On Windows run commands from WSL2 (recommended) or Git Bash so
`just` and the shell recipes work.

Existing local PostgreSQL 17 volumes need a one-time migration before using the PostgreSQL 18 compose service. See [`docs/postgresql-18-upgrade.md`](docs/postgresql-18-upgrade.md).

### Testing

- Full suite with the coverage gate CI enforces (Postgres + Meilisearch): `just coverage`
- Full suite without coverage: `just pytest`
- Fast focused tests (annotations + search services, SQLite in the api container): `just pytest-focused`
- Search-only tests: `just pytest-search`
- On the host, without Docker: `uv run pytest`. `conftest.py` switches to SQLite outside a container, and the search API tests that need a live Meilisearch skip.

### Runtime environment contract

- `config/test.env` is the template for `config/.env` and the env the test recipes run with; every other recipe uses `config/.env`.
- `config/settings.py` reads `config/.env` on the host too (explicit container env wins). Its service URLs use in-network hostnames (`postgres`, `meilisearch`, `redis`) that do not resolve on the host, so a host-native `python manage.py` starts but fails on the first connection. Host-native tests work because they use SQLite.
- `DEBUG=false` turns on secure cookies, SSL redirect and HSTS (`SECURE_SSL_REDIRECT` and `SECURE_HSTS_SECONDS` override the last two), and startup fails if `SECRET_KEY` is unset or the insecure default.

## Deploy

Image: [GitHub Packages](https://github.com/orgs/archetype-pal/packages/container/package/backend). Staging/production deployments are orchestrated by the [infrastructure repo](https://github.com/archetype-pal/infrastructure) — `compose.yaml` in this repo is for local development and CI only. How a merge becomes an image is in [CONTRIBUTING.md](CONTRIBUTING.md#releases).

### Production checklist

The infrastructure repo's `env_file.example` is the full deployment env. Before running in production, ensure:

- **SECRET_KEY** — Set a strong random value; never use the default or values from `config/test.env`.
- **DEBUG** — Set to `false`.
- **ALLOWED_HOSTS** — Set to your domain(s), e.g. `yourdomain.com,api.yourdomain.com`.
- **DATABASE_URL** — Production Postgres URL (user, password, host, port, dbname). If unset, Django falls back to a SQLite file (`local.db`) without complaint.
- **CORS_ALLOWED_ORIGINS** / **CSRF_TRUSTED_ORIGINS** — Your frontend/origin URLs.
- **CELERY_BROKER_URL** / **CELERY_RESULT_BACKEND** — Redis URL. Celery is required: it runs search sync, reindexing and upload ingest.
- **MEILISEARCH_API_KEY** — Meilisearch's master key when it runs with one (recommended in production).
- **IIIF_HOST** — The browser-facing SIPI URL. Search documents carry image URLs, so reindex after changing it.
- **ADMIN_EMAILS** / **EMAIL_HOST** (and related `EMAIL_*` vars) — Set to receive email on uncaught backend errors (traceback + request info) via Django's `mail_admins` logging handler. Left blank/console-backend in dev and CI.

## Further documentation

- [`docs/search-architecture.md`](docs/search-architecture.md) — how the search modules fit together; read it before adding an index type.
- [`docs/search-operations.md`](docs/search-operations.md) — runbook for indexing, health checks and incident recovery.
- [`docs/tei-backup-migration.md`](docs/tei-backup-migration.md) and [`docs/postgresql-18-upgrade.md`](docs/postgresql-18-upgrade.md) — one-off procedures.
- Deployment, backup and runtime incidents: the [infrastructure repo](https://github.com/archetype-pal/infrastructure) (`docs/` there).

## License

Licensed under the [GNU Affero General Public License v3.0](LICENSE).

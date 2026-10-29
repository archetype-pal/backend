# Archetype Backend Guide

Setup, tests and the env contract are in [README.md](README.md). Workflow, the
checks CI runs and the code guardrails are in [CONTRIBUTING.md](CONTRIBUTING.md).
This file is the map an agent needs on top of those.

## Runtime Policy (Mandatory)
- Backend must run via Docker Compose.
- Do not run backend services directly on host Python for normal local development.
  Tests are the exception: host-native `uv run pytest` is supported and uses SQLite.
- The frontend also runs in Docker by default — `just up` in `../frontend`, where
  every justfile recipe executes inside the dev container. Host-native `pnpm dev`
  remains a supported alternative and needs its own `.env`.

## Backend Architecture
- Stack: Django + DRF + Celery (`pyproject.toml`, `config/settings.py`, `config/celery.py`).
- Project is organized by feature apps in `apps/*` — **12 of them**, declared in
  `scripts/check_architecture_boundaries.py`, which is the authoritative list and
  dependency graph (every app under `apps/` must have an entry there or the check fails):
  - `common`, `users`, `manuscripts`, `symbols_structure`, `scribes`,
    `annotations`, `annotation_standards`, `publications`,
    `pages`, `worksets`, `search`, `uploads`.
  - `annotation_standards` serves IIIF Presentation (`/api/v1/iiif/`) and W3C Web
    Annotation (`/api/v1/annotations-w3c/`).
  - `uploads` is the chunked backoffice image upload and JP2 ingest (`/api/v1/uploads/`).
- Routing root is `config/urls.py` with API under `/api/v1/*`.
- API docs:
  - OpenAPI schema: `/api/v1/schema/`
  - Swagger UI: `/api/v1/docs/`
- Search subsystem is registry-driven in `apps/search/*` and uses Meilisearch-oriented
  services and adapters. See [`docs/search-architecture.md`](docs/search-architecture.md).
- Auth:
  - Token auth (DRF token + Djoser) with login/logout/profile endpoints in `apps/users/*`.
  - Default permission is `IsAuthenticatedOrReadOnly`; management viewsets are
    superuser-gated via `apps/common/permissions.py`.
- Layout inside an app: `models` → `services/` (domain logic, no HTTP) →
  `serializers` (validation + mapping) → `views` (transport only), with
  `filters.py`/`signals.py`/`tasks.py` beside them. Shared viewset bases,
  filter backends, pagination, exceptions and the CSV writer live in `apps/common`.
- Storage:
  - Django media is file-system based (`storage/media`).
  - SIPI serves that directory as IIIF, through manuscript/publication media fields.

## Command Reference

### Backend-first workflow (run in this directory)
`just` lists every recipe. The common ones:
- Start/stop: `just up`, `just up-bg`, `just down`, `just restart-api`, `just build`
- Database: `just makemigrations`, `just migrate` (resyncs id sequences first),
  `just postgres-dump`, `just postgres-restore FILE`
- Test/quality: `just pytest`, `just pytest-focused`, `just pytest-search`, `just coverage`,
  `just lint`, `just format`, `just check-architecture`
- Search operations: `just setup-search-indexes`, `just sync-search-index item-parts`,
  `just sync-all-search-indexes`
- Utilities: `just shell`, `just bash`, `just celery_status`

### Workspace-wide stack (run in `../infrastructure`)
- `just up` / `just up-bg`
- `just down`
- `just migrate`
- `just shell`
- `just` (no recipe) lists everything

## Compose Topology Notes
- `api/compose.yaml` (project `archetype-dev`) is local dev and CI only. Services:
  api, celery, postgres, meilisearch, redis, image_server. It exposes:
  - API on `localhost:8000`
  - Meilisearch on `localhost:7700`
  - Postgres on `localhost:5432`
  - Redis on `localhost:6379`
  - SIPI on `127.0.0.1:8182`
- `infrastructure/compose.yaml` (project `archetype`) is full-stack/proxy-centric and
  exposes nginx (`80`, `443`) and shared services. The distinct project names keep the
  two stacks' containers and volumes apart, so both can run at once.

## Frontend Coordination
- The frontend dev container (`just up` in `../frontend`) already points at this stack
  (`http://localhost:8000`). A host-native `pnpm dev` takes `NEXT_PUBLIC_API_URL` from
  its `.env` — a reachable backend URL with no trailing slash.

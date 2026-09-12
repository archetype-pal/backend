# Archetype Backend Guide

## Runtime Policy (Mandatory)
- Backend must run via Docker Compose.
- Do not run backend services directly on host Python for normal local development.
- The frontend also runs in Docker by default — `just up` in `../frontend`, where
  every justfile recipe executes inside the dev container. Host-native `pnpm dev`
  remains a supported alternative and needs its own `.env`.

## Backend Architecture
- Stack: Django + DRF + Celery (`pyproject.toml`, `config/settings.py`, `config/celery.py`).
- Project is organized by feature apps in `apps/*` — **12 of them**, declared in
  `scripts/check_architecture_boundaries.py`, which is the authoritative list
  (every app under `apps/` must have an entry there or the check fails):
  - `common`, `users`, `manuscripts`, `symbols_structure`, `scribes`,
    `annotations`, `annotations_w3c`, `iiif_presentation`, `publications`,
    `pages`, `worksets`, `search`.
  - `apps/uploads/` is **not** an app: it holds only stale `__pycache__` from a
    removed one, is untracked, and appears in neither `INSTALLED_APPS` nor the
    boundary graph.
- Routing root is `config/urls.py` with API under `/api/v1/*`.
- API docs:
  - OpenAPI schema: `/api/v1/schema/`
  - Swagger UI: `/api/v1/docs/`
- Search subsystem is registry-driven in `apps/search/*` and uses Meilisearch-oriented services and adapters.
- Auth:
  - Token auth (DRF token + Djoser) with profile/login endpoints in `apps/users/*`.
  - Management viewsets are superuser-gated via common permissions/views.
- Storage:
  - Django media is file-system based (`storage/media`).
  - IIIF image server integration exists via SIPI and manuscript/publication media fields.

## Command Reference

### Backend-first workflow (run in this directory)
- Start/stop:
  - `just up`
  - `just up-bg`
  - `just down`
  - `just restart-api`
- Database:
  - `just makemigrations`
  - `just migrate`
- Test/quality:
  - `just pytest`
  - `just pytest-focused`
  - `just pytest-search`
  - `just coverage`
- Search operations:
  - `just setup-search-indexes`
  - `just sync-search-index item-parts`
  - `just sync-all-search-indexes`
- Utilities:
  - `just shell`
  - `just bash`
  - `just celery_status`

### Workspace-wide stack (run in `../infrastructure`)
- `just up` / `just up-bg`
- `just down`
- `just migrate`
- `just shell`
- `just` (no recipe) lists everything

## Compose Topology Notes
- `api/compose.yaml` is backend-centric and exposes:
  - API on `localhost:8000`
  - Meilisearch on `localhost:7700`
  - Postgres on `localhost:5432`
  - Redis on `localhost:6379`
- `infrastructure/compose.yaml` is full-stack/proxy-centric and exposes nginx (`80`, `443`) and shared services.

## Frontend Coordination
- Frontend runs from `../frontend` using `pnpm dev`.
- Ensure frontend `NEXT_PUBLIC_API_URL` points to a reachable backend URL for the chosen compose mode.

# Archetype Backend Guide

## Runtime Policy (Mandatory)
- Backend must run via Docker Compose.
- Do not run backend services directly on host Python for normal local development.
- Frontend may run directly with `pnpm` from `../frontend`.

## Backend Architecture
- Stack: Django + DRF + Celery (`pyproject.toml`, `config/settings.py`, `config/celery.py`).
- Project is organized by feature apps in `apps/*`:
  - `common`, `users`, `scribes`, `symbols_structure`, `annotations`, `manuscripts`, `publications`, `search`.
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
  - `make up`
  - `make up-bg`
  - `make down`
  - `make restart-api`
- Database:
  - `make makemigrations`
  - `make migrate`
- Test/quality:
  - `make pytest`
  - `make pytest-focused`
  - `make pytest-search`
  - `make coverage`
- Search operations:
  - `make setup-search-indexes`
  - `make sync-search-index INDEX=item-parts`
  - `make sync-all-search-indexes`
- Utilities:
  - `make shell`
  - `make bash`
  - `make celery_status`

### Workspace-wide stack (run in `../infrastructure`)
- `make up`
- `make up-background`
- `make down`
- `make migrate`
- `make shell`

## Compose Topology Notes
- `api/compose.yaml` is backend-centric and exposes:
  - API on `localhost:8000`
  - Meilisearch on `localhost:7700`
  - Postgres on `localhost:5432`
  - Redis on `localhost:6379`
  - pgAdmin on `localhost:5050`
- `infrastructure/compose.yaml` is full-stack/proxy-centric and exposes nginx (`80`, `443`) and shared services.

## Frontend Coordination
- Frontend runs from `../frontend` using `pnpm dev`.
- Ensure frontend `NEXT_PUBLIC_API_URL` points to a reachable backend URL for the chosen compose mode.

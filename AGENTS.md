# Archetype Workspace Guide (Backend + Frontend)

This file gives Cursor quick architectural context and reliable commands for both repositories.

## Repositories

- Backend: `/Users/elgharee/hub/archetype/backend`
- Frontend: `/Users/elgharee/hub/archetype/frontend`

---

## Backend Architecture (Django + DRF)

- Runtime: Docker Compose (`compose.yaml`) is the canonical local/CI environment.
- Entry points: `manage.py`, DRF API under `/api/v1/*`, docs at `/api/v1/docs`.
- Main code: `apps/*` feature modules (`annotations`, `manuscripts`, `publications`, `scribes`, `search`, `users`).
- Search: registry-driven metadata in `apps/search/registry.py`; admin/search orchestration in `apps/search/admin_service.py` and `apps/search/services.py`.
- Config: `config/settings.py`, env contract from `config/test.env` (copy to `config/.env` for local runs).

### Backend Commands

Run from `/Users/elgharee/hub/archetype/backend`.

- Start stack: `docker compose up` (or `make up-bg` for detached)
- Stop stack: `make down`
- Migrations: `make makemigrations` / `make migrate`
- Django shell: `make shell`
- Tests (all): `make pytest`
- Tests (search only): `make pytest-search`
- Coverage gate: `make coverage`
- Search setup: `make setup-search-indexes`
- Reindex one search index: `make sync-search-index INDEX=item-parts`
- Reindex all search indexes: `make sync-all-search-indexes`
- Architecture checks: `make check-architecture` and `make check-ci-entrypoints`

---

## Frontend Architecture (Next.js App Router)

- Framework: Next.js (App Router), TypeScript, React Query, Tailwind.
- Main routes/layout: `app/*` (including backoffice UI in `app/backoffice/*`).
- UI building blocks: `components/ui/*` and feature components in `components/*`.
- Data access: `services/*` (API calls), with shared helpers in `lib/*`, `hooks/*`, `contexts/*`, `stores/*`.
- Search/backoffice wiring: search admin page in `app/backoffice/search-engine/page.tsx` and API client logic in `services/backoffice/*`.

### Frontend Commands

Run from `/Users/elgharee/hub/archetype/frontend`.

- Dev server: `pnpm dev`
- Dev against local backend: `pnpm dev:mock` (sets `NEXT_PUBLIC_API_URL=http://localhost:8000`)
- Build: `pnpm build`
- Start prod build: `pnpm start`
- Lint: `pnpm lint` (fix: `pnpm lint:fix`)
- Format check: `pnpm format` (fix: `pnpm format:fix`)
- Tests: `pnpm test` (watch: `pnpm test:watch`)

---

## Cross-Repo Workflow

- Run backend and frontend in parallel (ports: backend 8000, frontend 3000).
- Typical local loop:
  1. Start backend stack and apply migrations.
  2. Start frontend with `pnpm dev` (or `pnpm dev:mock`).
  3. Validate affected tests/lint in the repo you changed.

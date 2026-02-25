# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Archetype is a Django 6 / DRF backend for digital palaeography research. See `README.md` for stack details and `CONTRIBUTING.md` for code-style rules.

### Running services

All services run via Docker Compose. See `compose.yaml` and `Makefile` for commands.

```
sudo dockerd &>/tmp/dockerd.log &   # start Docker daemon (if not running)
sudo docker compose up -d            # start all services (api on :8000, meilisearch on :7700, postgres, redis, celery)
sudo docker compose run --rm api python manage.py migrate   # first-time only
```

The Django dev server (with hot reload) runs inside the `api` container on port 8000 (mapped from container port 80). Source code is volume-mounted at `/app`.

### Linting and type checking

```
uv run ruff check          # linter (one pre-existing E402 in conftest.py is expected)
uv run mypy apps config    # type checker
```

See `pyproject.toml` `[tool.ruff]` for config. `ruff format` for auto-formatting.

### Running tests

- **Full suite (Docker, recommended):** `API_ENV_FILE=config/test.env sudo -E docker compose run --rm api python -m pytest`
  - Requires all Docker services running (postgres, meilisearch, redis).
  - One pre-existing failure in `test_carousel_items_api` due to file-permission in the Docker image (non-root user).
- **Partial suite (local, no Docker services needed):** `USE_SQLITE_FOR_TESTS=1 uv run pytest`
  - Skips search API tests that require Meilisearch.
  - The `USE_SQLITE_FOR_TESTS=1` env var is **required** in Cloud Agent VMs because `/.dockerenv` exists (the VM itself is a container), which prevents `conftest.py` from auto-switching to SQLite.

### Gotchas

- `config/.env` must exist before Django starts. Copy from `config/test.env` if missing.
- Auth API endpoints do **not** use trailing slashes (e.g., `/api/v1/auth/token/login` not `/api/v1/auth/token/login/`).
- The compose.yaml postgres service does not expose port 5432 to the host — Django must run inside Docker (the `api` service) or you must add a port mapping.
- Python 3.14 is required (`requires-python = ">=3.14"` in `pyproject.toml`). Install via `uv python install 3.14`.

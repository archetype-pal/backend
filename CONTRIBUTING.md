# Contributing to Archetype
Thank you for your interest in contributing! 🎉

Local setup and test commands are in [README.md](README.md).

## How to Contribute
We use Pull Requests and feature branches for contributions.  
Also make sure your commits follow [Conventional Commits specification](https://conventionalcommits.org).  
Most of the time you will want to have an issue -assigned to you- created first.

1. **Fork the repository** (skip if you're a member on the archetype organization)
2. **Create a new branch** (`git checkout -b feat-XXX/changes-describing-title`)
3. **Make your changes**
4. **Test your changes**
5. **Commit your changes** (`git commit -m 'feat: adding something here!'`)
6. **Push to your fork (or directly)** (`git push origin feat-XXX/changes-describing-title`)
7. **Open a Pull Request**

### Branch naming
the branch name should start with the [type of changes](https://medium.com/@noriller/docs-conventional-commits-feat-fix-refactor-which-is-which-531614fcb65a) (feature, fix, etc).

followed by the issue number for this PR, if it exists.

## Checks CI runs
A pull request needs these green (`.github/workflows/ci.yml`). Run them before you push:

- `uv lock --check` — the lockfile matches `pyproject.toml`.
- `uvx ruff check` and `uvx ruff format --check .` — Ruff does linting and formatting (replacing pylint, black, and isort). `uvx ruff format .` or `just format` fixes formatting.
- `uvx mypy apps config` — type check.
- `uv run python scripts/check_architecture_boundaries.py` (`just check-architecture`) — inter-app imports follow the declared dependency graph.
- `USE_SQLITE_FOR_TESTS=1 uv run python manage.py makemigrations --check --dry-run` — no model change is missing its migration.
- `just coverage` — the full suite on Postgres and Meilisearch, failing under 55% coverage.

The Security workflow also runs CodeQL and a `pip-audit` of the locked dependencies on every push and pull request, and weekly.

`.githooks/pre-commit` runs the Ruff checks, `uv lock --check` and the boundary check. It is opt-in per clone (`git config core.hooksPath .githooks`) and skips mypy, the migrations check and the tests, so a clean commit does not mean a green CI.

## Code guardrails
- Keep views transport-only (validation, HTTP mapping, response shape); move orchestration and Celery task dispatch into application services. A new `@action` ships with an input serializer and a service function; the view body maps one onto the other (see `apps/manuscripts/views/image_texts.py`).
- Keep serializer responsibilities to validation + mapping; mutation workflows belong in domain services. `services/`, `serializers/`, `models`, `signals` and `filters` never import from `views` (the architecture check enforces this).
- Every routed operation is documented in its app's `schema.yaml` (`test_schema_yaml_consistency` fails otherwise); standard CRUD entries can be copied from a sibling.
- Comments explain the rule and link the issue; do not record project phases or roadmap labels in code.
- Reuse shared contracts/registries before adding new branching logic.
- A new app needs an entry in `scripts/check_architecture_boundaries.py` declaring which apps it may import.
- Search index metadata is registry-driven (`apps/search/registry.py`). When adding a new index type, update registry + builder + tests together; see [`docs/search-architecture.md`](docs/search-architecture.md).

## Test guardrails
- Test behaviour through real rows and the HTTP surface (factories + `api_client` / `authenticated_client` / `management_client` fixtures). Avoid `SimpleNamespace`/`MagicMock` stand-ins for models or querysets: they mirror today's ORM shape and hide the bugs a shape change causes. Mock only the external services (Meilisearch, SIPI, the broker, SMTP).
- Do not write a test for a constant, a seed value, a framework feature or a mock being called; a test should fail for a behavioural reason.
- Permission checks on `management/` routes are covered once, for every routed operation, by `apps/common/tests/test_management_permissions.py`; do not add per-endpoint 401/403 tests there. Likewise `test_schema_yaml_consistency` (schema ↔ routes ↔ `$ref`s) and `apps/search/tests/test_registry_drift.py` (registry ↔ builders ↔ dependencies).
- Prefer one parametrized test over a row of near-identical ones, and one test per behaviour over one per assertion.

## Releases
- After CI passes on `main`, CD (`.github/workflows/cd.yml`) publishes `ghcr.io/archetype-pal/backend` as `:latest` and an immutable `:sha-<commit>`, checks the image starts, then scans it with Trivy (HIGH/CRITICAL with a fix available). The build passes the day's date as `APT_REFRESH`, so the first build each day reruns the OS-patch layer instead of reusing it from cache.
- The scan runs after the push, so a red scan does not stop the image from being deployed. Treat it as urgent.
- Beta deploys the newest `:latest` by itself: a timer on the host checks the registry every three minutes and runs the infrastructure repo's `scripts/deploy.sh`, which migrates, runs `collectstatic`, applies the search index settings and rolls back if its smoke test fails. To roll back by hand, run that repo's `deploy-beta` workflow with an earlier `ghcr.io/archetype-pal/backend:sha-<commit>` as its backend image; the pin holds until the next image is published. Details: `docs/beta-deployment.md` in the [infrastructure repo](https://github.com/archetype-pal/infrastructure).
- `cd-staging.yml` promotes a chosen `sha-<commit>` tag to `:staging` by hand.
- Deploys do not rebuild search indexes. A change to a document builder or the registry's attribute lists needs a reindex; see [`docs/search-operations.md`](docs/search-operations.md).

## Reporting Bugs / Requesting Features
- Use [GitHub Issues](https://github.com/archetype-pal/backend/issues) to report bugs or request features.
- Please include steps to reproduce and as much detail as possible.

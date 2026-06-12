# Repository Review (Security, Maintainability, Code Style, Good Practices)

Date: 2026-06-10
Scope: backend repository review based on source inspection and targeted dependency CVE checks.

## Findings (ordered by severity)

### 1) High - Any authenticated user can create/update/delete annotations globally
- Evidence:
  - `apps/annotations/urls.py:7` exposes `annotations/graphs` through `GraphViewerWriteViewSet`.
  - `apps/annotations/views.py:43-56` uses only `IsAuthenticated` for write operations (`post`, `patch`, `delete`).
  - `apps/annotations/models.py` has no ownership field on `Graph`, so object-level ownership cannot be enforced.
- Risk:
  - Any authenticated account can modify or delete any graph annotation record, causing integrity loss and possible vandalism.
- Recommendation:
  - Restrict this endpoint to privileged roles (`IsSuperuser` / staff / dedicated annotator permission).
  - If collaborative editing is required, add ownership/editor-role model and object-level authorization checks.
  - Add tests for unauthorized write attempts across tenants/users.

### 2) High - Internal annotation notes are exposed to all authenticated users
- Evidence:
  - `apps/annotations/serializers.py:95-100` returns `internal_note` whenever user is authenticated.
  - `apps/annotations/views.py:37-40` gives authenticated users full graph queryset (including editorial types).
- Risk:
  - Internal research/editorial notes may leak to non-privileged users.
- Recommendation:
  - Gate `internal_note` behind staff/superuser checks or remove from non-management serializer.
  - Ensure public/viewer serializers and management serializers are strictly separated by role.

### 3) High - Insecure credential handling in tracked config files
- Evidence:
  - `compose.yaml:27` hardcoded `POSTGRES_PASSWORD`.
  - `compose.yaml:37-38` `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD=admin`.
  - `config/test.env:5,12` committed secret-like values and DB URL with password.
- Risk:
  - Credential reuse, accidental exposure, and unsafe defaults copied into non-local environments.
- Recommendation:
  - Move secrets to untracked env files or secret manager; commit only `.env.example` placeholders.
  - Use non-default generated dev credentials per machine.
  - Add secret scanning in CI/pre-commit.

### 4) Medium - Public W3C graph endpoint allows object-id enumeration
- Evidence:
  - `apps/annotations_w3c/views.py:46-52` `graph_annotation` is public (`@permission_classes([])`) and fetches `Graph` by id directly.
- Risk:
  - Enumeration of graph IDs can expose notes/metadata that may not be intended for broad public access.
- Recommendation:
  - Add visibility constraints (e.g., only graphs linked to public `ImageText` states).
  - Consider opaque identifiers or stronger filtering by publication status.

### 5) Medium - Swagger UI depends on third-party CDN scripts without integrity pinning
- Evidence:
  - `apps/common/templates/swagger-ui.html:11,16,17` loads assets from `unpkg.com` using protocol-relative URLs.
- Risk:
  - Supply-chain/client-side integrity risk and non-deterministic docs UI behavior.
- Recommendation:
  - Serve pinned Swagger assets locally or pin exact versions with SRI hashes over HTTPS.

### 6) Medium - Production hardening settings are incomplete in Django settings
- Evidence:
  - `config/settings.py` defines `SECURE_PROXY_SSL_HEADER` (`:64`) but does not define common hardening flags such as `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS settings.
- Risk:
  - Easier misconfiguration when deploying behind reverse proxies; weaker transport/cookie security defaults.
- Recommendation:
  - Add environment-driven security flags for production profile and document required values.

### 7) Medium - Non-reproducible container base/image versions
- Evidence:
  - `compose.yaml` uses floating tags: `getmeili/meilisearch:latest`, `dpage/pgadmin4:latest`, `ghcr.io/archetype-pal/backend:latest`.
- Risk:
  - Unexpected breaking changes and harder rollback/debug across environments.
- Recommendation:
  - Pin image versions/digests for reproducible builds.

### 8) Medium - Dependency CVEs found in pinned minimums (Pillow)
- Evidence:
  - CVE validation result for `pillow@12.1.1`: 5 known CVEs (including high severity), fixed in `12.2.0+`.
- Risk:
  - Potential denial-of-service/memory-corruption paths via crafted files.
- Recommendation:
  - Upgrade to `pillow>=12.2.0` in `pyproject.toml` and refresh lockfile.

### 9) Low - Very large view module hurts maintainability and reviewability
- Evidence:
  - `apps/manuscripts/views.py` is ~755 lines and mixes many concerns (public reads, management writes, exports, workflow actions).
- Risk:
  - Higher regression probability, harder onboarding, harder permission auditing.
- Recommendation:
  - Split by bounded context (public API, management API, import/export actions, workflow actions).

### 10) Low - No CI workflow found in repository
- Evidence:
  - No files found under `.github/workflows/*` in this workspace.
- Risk:
  - Lint/tests/security checks may run inconsistently and regressions may slip in.
- Recommendation:
  - Add CI for `ruff`, `pytest`, coverage threshold, and dependency/security scanning.

## Maintainability and Code Style Notes

### Strengths observed
- Good use of typed hints and modern Python typing across many modules.
- Reusable privileged base classes (`apps/common/views.py`) reduce repeated permission boilerplate.
- CSV export includes CSV-injection mitigation (`apps/manuscripts/views.py:683-697`) - good security hygiene.
- Architecture boundary utility exists (`scripts/check_architecture_boundaries.py`) and a `just` workflow is documented.

### Opportunities
- Centralize repeated "public visibility" logic (Live/Reviewed filtering) into one reusable utility to avoid drift.
- Keep serializers role-specific; avoid exposing management-oriented fields in broadly accessible endpoints.
- Add explicit threat-model notes for endpoints intentionally public with no auth.

## Suggested Priority Plan

1. Lock down annotation write/read authorization (`apps/annotations/*`) and add tests.
2. Remove committed credentials and rotate local defaults.
3. Upgrade Pillow to a non-vulnerable version and refresh lockfile.
4. Pin container image versions and harden production security settings.
5. Add CI quality/security gates.
6. Refactor oversized modules incrementally.

## Review Limitations
- This is a source-level review; no runtime pen-test was executed.
- Findings are based on current repository state and visible configuration.
- Deployment-specific protections (proxy/WAF/network ACLs) were not evaluated here.


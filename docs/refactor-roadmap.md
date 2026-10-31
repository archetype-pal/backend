# Refactor roadmap: open items

The consolidation pass (dead code, duplicates, view orchestration moved into
serializers + services, module layout, dependency edges, schema coverage,
the DigiPal migration tooling, the search stack) has shipped. What it
established is now enforced rather than described:

- `scripts/check_architecture_boundaries.py` — app dependency graph
  (`ALLOWED_DEPS`) and "no `services/` / `serializers/` / models / signals /
  filters importing from a `views` module".
- `test_every_route_is_documented` — every routed operation has a
  `schema.yaml` entry.
- `apps/search/tests/test_registry_drift.py` and
  `test_reindex_query_counts.py` — registry/builder agreement and constant
  query counts per index.
- CONTRIBUTING: "an action is a serializer + a service call", no project
  phase labels in code, schema rule; AGENTS.md: where a module goes.

The search contract changes that needed a frontend check shipped too
(backend#272, frontend#269): pruned `_formatted`, natural shelfmark sort,
date bounds on hands and images, `catalogue_numbers` as a list everywhere,
`gte` / `lte`, `export?download=1`, `GET /search/{index}/meta/`; the
transitional endpoints and aliases came out in backend#273. "Search
contract" in `search-architecture.md` describes the result.

This file lists only what is still open; the longer-term structural
direction is in `architecture-proposal.md`.

---

## 1. With the frontend

- Sort and facet controls built from `GET /search/{index}/meta/` and the
  page's `total` / `limit` / `offset`; then drop the absolute `next` /
  `previous` / `ordering.options` URLs from the facets response.

## 2. Needs `uv lock` (dependency changes)

| Item | Detail |
|---|---|
| `defusedxml` for untrusted XML | The HTR parsers (`services/htr/alto.py`, `services/htr/page_xml.py`) and TEI validation (`services/tei/validate.py`) parse caller-supplied XML with stdlib `xml.etree`. `defusedxml` is already a transitive dependency; declare it and use `defusedxml.ElementTree` at those entry points. |
| Prune direct dependencies | `python-dateutil` is used by one test factory only → dev group. `idna`, `pyjwt`, `cryptography` are not imported by project code → either a "CVE floor" comment like `social-auth-app-django` carries, or let them become transitive. |
| `SEARCH_AUTO_REINDEX` → `SEARCH_AUTO_SYNC` | The flag gates incremental *sync*, not reindexing. Rename in settings, `.env` templates, `search-operations.md` and `tei-backup-migration.md`; keep the old name as an alias for one release. (No lock change; listed here because it is an environment change to coordinate with the infrastructure repo.) |

## 3. CI guardrails still to switch on

Both need a green run on a machine with the toolchain to calibrate the
allow-lists; neither should be enabled blind.

- `vulture apps config --min-confidence 80` with a small allow-list
  (DRF/Django hooks such as `get_queryset`, `perform_create`, signal
  receivers and `Meta` attributes look unused to it).
- Ruff `PLR0915` with a generous statement limit (~60) so the next 100-line
  view action fails review mechanically rather than by eye. (`C4`, `SIM`,
  `PERF`, `RET` and `PIE` are on since backend#277.)

## 4. Style debt that is not worth a dedicated pass

Fix when touching the file:

- The `APITestCase` classes in the per-app `tests/tests.py` modules could
  be pytest-style modules like the newer tests; converting them is churn
  with no behavioural gain.
- A few public serializers are still declared in full rather than as a
  subclass of their management twin because their nested vs pk fields
  differ. Leave them unless the shapes converge.

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
- Ruff `PLR0915`: no function over 60 statements.

The search contract changes that needed a frontend check shipped too
(backend#272, frontend#269): pruned `_formatted`, natural shelfmark sort,
date bounds on hands and images, `catalogue_numbers` as a list everywhere,
`gte` / `lte`, `export?download=1`, `GET /search/{index}/meta/`; the
transitional endpoints and aliases came out in backend#273. "Search
contract" in `search-architecture.md` describes the result.

This file lists what is still open and what was checked and dropped; the
longer-term structural direction is in `architecture-proposal.md`.

---

## 1. With the frontend

- Sort and facet controls built from `GET /search/{index}/meta/` and the
  page's `total` / `limit` / `offset`; then drop the absolute `next` /
  `previous` / `ordering.options` URLs from the facets response.

## 2. Considered and dropped

Checked on 2026-11-03 against the backend image (Python 3.15, expat 2.9.0).

- **`defusedxml` at the XML entry points.** The bundled expat rejects
  entity amplification ("billion laughs") with a `ParseError`, and
  `xml.etree` never loads an external entity. TEI validation, the msDesc
  parser and the TEI formatter wrap a fragment in a root element, so a
  DOCTYPE cannot occur there at all. Only the HTR parsers take a whole
  document, and expat covers them.
- **`vulture` in CI.** At 80% confidence it reports only pytest fixtures
  (used by name) and a DRF parser's required signature; ruff already
  catches unused imports and variables. At 60% it prints 456 lines, almost
  all Django and DRF hooks.

## 3. Style debt that is not worth a dedicated pass

Fix when touching the file:

- The `APITestCase` classes in the per-app `tests/tests.py` modules could
  be pytest-style modules like the newer tests; converting them is churn
  with no behavioural gain.
- A few public serializers are still declared in full rather than as a
  subclass of their management twin because their nested vs pk fields
  differ. Leave them unless the shapes converge.

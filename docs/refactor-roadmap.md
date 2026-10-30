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

This file lists only what is still open. Search-specific items are in
`search-roadmap.md`; the longer-term structural direction is in
`architecture-proposal.md`.

---

## 1. Needs the frontend first

| Item | Why it is still here | What to do |
|---|---|---|
| `GET management/scribes/get_item_images/` | Same data as `management/item-images/?item_part=`. It is the only code path carrying the `scribes → manuscripts` import edge. | Switch the frontend, delete the action, drop `manuscripts` from `scribes`' allowed deps in the boundary checker. |
| `GET search/management/image-texts/overview/` | Alias of `manuscripts/management/image-texts/overview/` kept for the dashboard. | Switch the frontend, delete the alias route and its schema entry. |
| `CatalogueNumber.catalogue` / `HistoricalItemDescription.source` payloads | Fixed to a real `BibliographicSourceSerializer`; the accidental `url: null` key is gone. | Confirm nothing in the frontend read `url` on those objects. Nothing else to do. |

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
- Ruff `C4` (comprehensions), `SIM` (simplify) and `PLR0915` with a generous
  statement limit (~60) so the next 100-line view action fails review
  mechanically rather than by eye.

## 4. Style debt that is not worth a dedicated pass

Fix when touching the file:

- The `APITestCase` classes in the per-app `tests/tests.py` modules could
  be pytest-style modules like the newer tests; converting them is churn
  with no behavioural gain.
- A few public serializers are still declared in full rather than as a
  subclass of their management twin because their nested vs pk fields
  differ. Leave them unless the shapes converge.

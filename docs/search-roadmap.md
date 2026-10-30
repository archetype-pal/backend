# Search: open items

Scope: `apps/search` and the HTTP contract the frontend consumes. Read
`search-architecture.md` for how the stack works and `search-operations.md`
for the runbook. Everything backend-only from the original assessment
(fail-safe incremental sync, visible Meilisearch failures, constant query
counts per index, offline HTTP tests, registry drift guards, TEI-native
extraction, cached fan-out counts, adaptive reindex lock) has shipped and is
pinned by tests under `apps/search/tests/`.

The contract changes that needed a frontend check have shipped too, each
behind the old behaviour (see "Search contract" in `search-architecture.md`):

- `_formatted` carries only the searchable attributes, and the `texts` list
  crops `content`. Result cards still read `coordinates` /
  `annotation_coordinates`, so those stay in the raw hit.
- `catalogue_numbers` is a list on every index; `status` is no longer a
  default facet on the public text indexes; `date_min` / `date_max` are
  filterable and sortable on `hands` and `item-images` too; `shelfmark`
  sorts naturally through a `shelfmark_sort` alias the reader applies.
- The query builder accepts `gte` / `lte`; `gt` / `lt` still compile to the
  same thing.
- `export?download=1` serves the file itself; the JSON wrapper is still the
  default.
- `GET /search/{index}/meta/` exposes each index's attribute lists.

---

## With the frontend

Each item is a frontend change; the backend side is already in place. Remove
the transitional behaviour here once the frontend has moved.

- Results table: join array cells (`catalogue_numbers` on every index, the
  `hands` columns already) with `, ` — today arrays render concatenated.
  Then drop the `string` typing of `catalogue_numbers` on the text-derived
  and hand item types.
- Query builder: send `gte` / `lte`; then drop the `gt` / `lt` aliases in
  `qb_parser.py`.
- Export: request `download=1` and save the response; then drop the
  `{"content": …}` wrapper.
- Sort and facet controls: build them from `/meta/` and the page's
  `total` / `limit` / `offset`; then drop the absolute `next` / `previous` /
  `ordering.options` URLs from the facets response.

## Outside this repository

- Run `setup_search_indexes` in the post-deploy step next to `migrate`
  (infrastructure repository) so a new facet never 400s. A *builder* change
  still needs a reindex; the runbook covers that.

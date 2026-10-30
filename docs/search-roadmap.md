# Search: open items

Scope: `apps/search` and the HTTP contract the frontend consumes. Read
`search-architecture.md` for how the stack works and `search-operations.md`
for the runbook. Everything backend-only from the original assessment
(fail-safe incremental sync, visible Meilisearch failures, constant query
counts per index, offline HTTP tests, registry drift guards, TEI-native
extraction, cached fan-out counts, adaptive reindex lock) has shipped and is
pinned by tests under `apps/search/tests/`.

What remains needs a frontend change, so each item is a small contract
change to agree on, ship behind the old behaviour, and then remove.

---

## Step 4 — Trim the response (P1, ~½ day, frontend check)

Today the reader asks Meilisearch for `attributesToHighlight: ["*"]`, so every
hit comes back twice: once raw and once as `_formatted`. On the `texts`
index that is the whole transcription twice, plus `coordinates` /
`annotation_coordinates` JSON strings nobody highlights. Restricting
highlighting alone does not shrink `_formatted` — `attributesToRetrieve`
must change too.

- Highlight only the index's `searchable_attributes`; crop `content` in list
  results (`attributesToCrop` + `cropLength`). The frontend already renders a
  cropped `_formatted.content` in suggestions.
- Default `attributesToRetrieve` per index to what the result cards read;
  drop `coordinates` / `annotation_coordinates` unless
  `?attributes_to_retrieve` asks for them.
- Needs one look at the frontend card components before shipping. No
  reindex.

## Step 8 — Document shape consistency (P2, ~1 day, reindex required, frontend coordination)

Each inconsistency below is a special case in the frontend today.

- `catalogue_numbers` is a list on `hands` and a joined string everywhere
  else → list everywhere (it is a multi-valued facet candidate).
- `status` is a facet on the public text indexes whose rows are only ever
  `Live` / `Reviewed` → drop it from the public facets.
- `date` is a string facet next to numeric `date_min` / `date_max` → keep
  `date` as display only; `date_min` / `date_max` are the numeric facets on
  every dated index.
- `type` means "historical item type" on most indexes while the text indexes
  carry the text's kind in `text_type` → keep both names, document that
  `type` is always the historical-item type.
- Natural sort for `shelfmark` (`MS 2` before `MS 10`): add a
  `shelfmark_sort` attribute and point `sortable_attributes` at it.

Ship as: builder + registry change, `setup_search_indexes`, full reindex,
frontend switch, then remove the old attributes on the next reindex.

## Also with the frontend (P3)

- Query-builder `gt` / `lt` compile to `>=` / `<=` → rename to `gte` / `lte`
  (accept both during the transition).
- `export` returns CSV and BibTeX as `{"content": …}` → serve a real download
  (`text/csv`, `application/x-bibtex`) as the image-text export already
  does; keep the JSON wrapper until the frontend switches.
- The facets endpoint builds absolute `next` / `previous` / ordering URLs
  server-side → let the frontend build them from `total` / `limit` /
  `offset` and a per-index `GET /search/{index}/meta/` exposing
  `sortable_attributes`.

## Outside this repository

- Run `setup_search_indexes` in the post-deploy step next to `migrate`
  (infrastructure repository) so a new facet never 400s. A *builder* change
  still needs a reindex; the runbook covers that.

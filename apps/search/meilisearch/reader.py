import logging
from typing import Any

from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

from apps.search.meilisearch.client import MeilisearchAdapter
from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.registry import get_registration
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

# Sentinel tags wrapping matched terms in Meilisearch `_formatted` output. The
# frontend swaps these for <mark>; kept as opaque tokens (not real HTML) so the
# markup survives transport without being sanitised away.
HIGHLIGHT_PRE_TAG = "__hl_start__"
HIGHLIGHT_POST_TAG = "__hl_end__"


class MeilisearchIndexReader(MeilisearchAdapter):
    def _build_search_params(
        self,
        index_type: IndexType,
        search_query: SearchQuery,
        facet_attributes: list[str] | None = None,
    ) -> tuple[str, str, dict[str, Any]]:
        uid = self._index_uid(index_type)

        filter_expr = build_meilisearch_filter(search_query.filter_spec)
        sort_list = [str(search_query.sort_spec)] if search_query.sort_spec else None

        # `contains` / `starts_with` have no Meilisearch filter form: they become
        # extra query terms, restricted to the attribute they name.
        spec = search_query.filter_spec
        searchable = set(get_registration(index_type).searchable_attributes)
        attrs_to_search = list(search_query.attributes_to_search_on)
        q_parts = [(search_query.q or "").strip()]
        for field, value in {**spec.contains, **spec.starts_with}.items():
            if value and field in searchable:
                q_parts.append(value)
                if field not in attrs_to_search:
                    attrs_to_search.append(field)
        q_text = " ".join(part for part in q_parts if part)

        optional: dict[str, Any] = {
            "filter": filter_expr,
            "sort": sort_list,
            "facets": facet_attributes,
            "matchingStrategy": search_query.matching_strategy,
            "attributesToSearchOn": attrs_to_search,
            "attributesToRetrieve": search_query.attributes_to_retrieve,
            "attributesToCrop": search_query.attributes_to_crop,
            "cropLength": search_query.crop_length if search_query.attributes_to_crop else None,
        }
        options: dict[str, Any] = {
            "limit": search_query.limit,
            "offset": search_query.offset,
            "attributesToHighlight": ["*"],
            "highlightPreTag": HIGHLIGHT_PRE_TAG,
            "highlightPostTag": HIGHLIGHT_POST_TAG,
            **{key: value for key, value in optional.items() if value},
        }
        return uid, q_text, options

    def _to_search_result(self, body: dict[str, Any], search_query: SearchQuery) -> SearchResult:
        hits = body.get("hits", [])
        if not isinstance(hits, list):
            hits = []
        total = body.get("estimatedTotalHits", body.get("totalHits", len(hits)))
        limit = body.get("limit", search_query.limit)
        offset = body.get("offset", search_query.offset)
        return SearchResult(hits=hits, total=total, limit=limit, offset=offset)

    def search(
        self,
        index_type: IndexType,
        search_query: SearchQuery,
        facet_attributes: list[str] | None = None,
    ) -> tuple[SearchResult, FacetResult | None]:
        uid, q_text, opt_params = self._build_search_params(index_type, search_query, facet_attributes)
        index = self.client.index(uid)
        body: dict[str, Any] = index.search(q_text, opt_params)

        search_result = self._to_search_result(body, search_query)

        facet_result = None
        if facet_attributes:
            facet_result = FacetResult(
                facet_distribution=body.get("facetDistribution", {}),
                facet_stats=body.get("facetStats", {}),
            )

        return search_result, facet_result

    def multi_search(self, specs: list[tuple[IndexType, SearchQuery]]) -> list[tuple[IndexType, SearchResult]]:
        """Run several index searches in ONE Meilisearch round-trip (federated).

        Returns (index_type, SearchResult) pairs in the same order as `specs`.
        """
        if not specs:
            return []
        queries: list[dict[str, Any]] = []
        for index_type, search_query in specs:
            uid, q_text, opt_params = self._build_search_params(index_type, search_query)
            queries.append({"indexUid": uid, "q": q_text, **opt_params})

        body: dict[str, Any] = self.client.multi_search(queries)
        raw_results = body.get("results", []) if isinstance(body, dict) else []
        out: list[tuple[IndexType, SearchResult]] = []
        for (index_type, search_query), result_body in zip(specs, raw_results, strict=False):
            out.append((index_type, self._to_search_result(result_body, search_query)))
        return out

    def get_document_by_id(self, index_type: IndexType, document_id: int | str) -> dict | None:
        uid = self._index_uid(index_type)
        try:
            index = self.client.index(uid)
            doc = index.get_document(str(document_id))
            return dict(doc) if not isinstance(doc, dict) else doc
        except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.debug("Meilisearch get_document failed for %s doc %s: %s", uid, document_id, e)
            return None
        except Exception:
            logger.exception("Unexpected error in get_document_by_id for %s doc %s", uid, document_id)
            raise

"""Meilisearch search index reader."""

import logging
from typing import Any

from django.conf import settings
from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

from apps.search.meilisearch.client import get_meilisearch_client
from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.registry import get_registration
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

logger = logging.getLogger(__name__)


class MeilisearchIndexReader:
    """Read/search Meilisearch indexes using the SDK."""

    def __init__(self):
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_meilisearch_client()
        return self._client

    def _index_uid(self, index_type: IndexType) -> str:
        prefix = getattr(settings, "MEILISEARCH_INDEX_PREFIX", "") or ""
        return f"{prefix}{index_type.uid}".strip() or index_type.uid

    def search(
        self,
        index_type: IndexType,
        search_query: SearchQuery,
        facet_attributes: list[str] | None = None,
    ) -> tuple[SearchResult, FacetResult | None]:
        """Run search (and optionally facets). Returns (SearchResult, FacetResult or None)."""
        uid = self._index_uid(index_type)
        index = self.client.index(uid)

        filter_expr = build_meilisearch_filter(search_query.filter_spec, index_type)
        sort_list: list[str] | None = None
        if search_query.sort_spec:
            direction = "asc" if search_query.sort_spec.ascending else "desc"
            sort_list = [f"{search_query.sort_spec.attribute}:{direction}"]

        searchable = set(get_registration(index_type).searchable_attributes)
        extra_q_parts: list[str] = []
        attrs_to_search = list(search_query.attributes_to_search_on)
        for field, val in search_query.filter_spec.contains.items():
            if not val or field not in searchable:
                continue
            extra_q_parts.append(val)
            if field not in attrs_to_search:
                attrs_to_search.append(field)
        for field, val in search_query.filter_spec.starts_with.items():
            if not val or field not in searchable:
                continue
            extra_q_parts.append(val)
            if field not in attrs_to_search:
                attrs_to_search.append(field)
        q_text = (search_query.q or "").strip()
        if extra_q_parts:
            q_text = f"{q_text} {' '.join(extra_q_parts)}".strip()

        opt_params: dict[str, Any] = {
            "limit": search_query.limit,
            "offset": search_query.offset,
            "attributesToHighlight": ["*"],
            "highlightPreTag": "__hl_start__",
            "highlightPostTag": "__hl_end__",
        }
        if filter_expr:
            opt_params["filter"] = filter_expr
        if sort_list:
            opt_params["sort"] = sort_list
        if facet_attributes:
            opt_params["facets"] = facet_attributes
        if search_query.matching_strategy:
            opt_params["matchingStrategy"] = search_query.matching_strategy
        if attrs_to_search:
            opt_params["attributesToSearchOn"] = attrs_to_search
        if search_query.attributes_to_retrieve:
            opt_params["attributesToRetrieve"] = search_query.attributes_to_retrieve

        body: dict[str, Any] = index.search(q_text, opt_params)

        hits = body.get("hits", [])
        if not isinstance(hits, list):
            hits = []
        total = body.get("estimatedTotalHits", body.get("totalHits", len(hits)))
        limit = body.get("limit", search_query.limit)
        offset = body.get("offset", search_query.offset)

        search_result = SearchResult(hits=hits, total=total, limit=limit, offset=offset)

        facet_result = None
        if facet_attributes:
            facet_distribution = body.get("facetDistribution", {})
            facet_stats = body.get("facetStats", {})
            facet_result = FacetResult(
                facet_distribution=facet_distribution,
                facet_stats=facet_stats,
            )

        return search_result, facet_result

    def get_document_by_id(self, index_type: IndexType, document_id: int | str) -> dict | None:
        """Return one document by id or None if not found."""
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

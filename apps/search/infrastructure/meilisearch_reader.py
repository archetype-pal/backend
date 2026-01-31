"""Meilisearch implementation of ISearchIndexReader."""

from django.conf import settings

from apps.search.domain import FacetResult, IndexType, SearchQuery, SearchResult
from apps.search.infrastructure.client import get_meilisearch_client
from apps.search.infrastructure.filter_builder import build_meilisearch_filter
from apps.search.infrastructure.index_settings import SORTABLE_ATTRIBUTES


class MeilisearchIndexReader:
    """Implements ISearchIndexReader using Meilisearch SDK."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
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

        filter_expr = build_meilisearch_filter(search_query.filter_spec)
        sort_list = None
        if search_query.sort_spec:
            direction = "asc" if search_query.sort_spec.ascending else "desc"
            sort_list = [f"{search_query.sort_spec.attribute}:{direction}"]

        opt_params = {
            "limit": search_query.limit,
            "offset": search_query.offset,
        }
        if filter_expr:
            opt_params["filter"] = filter_expr
        if sort_list:
            opt_params["sort"] = sort_list
        if facet_attributes:
            opt_params["facets"] = facet_attributes

        body = index.search(search_query.q or "", opt_params)

        hits = body.get("hits", [])
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
        except Exception:
            return None

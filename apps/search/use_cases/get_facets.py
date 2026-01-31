"""Use case: GetFacets."""

from apps.search.domain import FacetResult, IndexType, SearchQuery
from apps.search.infrastructure.meilisearch_reader import MeilisearchIndexReader


class GetFacets:
    """Get facet counts (and stats) for an index, scoped to the current filter. Depends on ISearchIndexReader."""

    def __init__(self, reader: MeilisearchIndexReader | None = None):
        self._reader = reader or MeilisearchIndexReader()

    def __call__(
        self,
        index_type: IndexType,
        search_query: SearchQuery,
        facet_attributes: list[str],
    ) -> FacetResult:
        _, facet_result = self._reader.search(index_type, search_query, facet_attributes=facet_attributes)
        if facet_result is None:
            return FacetResult(facet_distribution={}, facet_stats={})
        return facet_result

"""Use case: SearchDocuments."""

from apps.search.domain import IndexType, SearchQuery, SearchResult
from apps.search.infrastructure.meilisearch_reader import MeilisearchIndexReader


class SearchDocuments:
    """Search documents in an index. Depends on ISearchIndexReader."""

    def __init__(self, reader: MeilisearchIndexReader | None = None):
        self._reader = reader or MeilisearchIndexReader()

    def __call__(self, index_type: IndexType, search_query: SearchQuery) -> SearchResult:
        result, _ = self._reader.search(index_type, search_query, facet_attributes=None)
        return result

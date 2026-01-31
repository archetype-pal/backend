"""Port: search index reader. Implemented by MeilisearchIndexReader."""

from typing import Protocol

from apps.search.domain import FacetResult, IndexType, SearchQuery, SearchResult


class ISearchIndexReader(Protocol):
    """Search and facet over an index. Returns DTOs only."""

    def search(
        self,
        index_type: IndexType,
        search_query: SearchQuery,
        facet_attributes: list[str] | None = None,
    ) -> tuple[SearchResult, FacetResult | None]:
        """
        Run search (and optionally facets). If facet_attributes is None, no facets.
        Returns (SearchResult, FacetResult or None).
        """
        ...

    def get_document_by_id(self, index_type: IndexType, document_id: int | str) -> dict | None:
        """Return one document by id or None if not found."""
        ...

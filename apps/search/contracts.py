from typing import Any, Protocol

from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

SearchDocument = dict[str, Any]


class SearchBackend(Protocol):
    """What `SearchService` needs from a read adapter (`meilisearch/reader.py` implements it)."""

    def search(
        self,
        index_type: IndexType,
        query: SearchQuery,
        *,
        facet_attributes: list[str] | None = None,
    ) -> tuple[SearchResult, FacetResult | None]: ...

    def multi_search(self, specs: list[tuple[IndexType, SearchQuery]]) -> list[tuple[IndexType, SearchResult]]: ...

    def get_document_by_id(self, index_type: IndexType, doc_id: int | str) -> SearchDocument | None: ...

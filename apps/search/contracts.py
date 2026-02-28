"""Contracts for search indexing and backend integrations."""

from collections.abc import Iterable
from typing import Any, Protocol

from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

SearchDocument = dict[str, Any]


class IndexDocumentBuilder(Protocol):
    """Build one or more searchable documents for a domain object."""

    def __call__(self, obj: Any) -> Iterable[SearchDocument]:
        ...


class SearchBackend(Protocol):
    """Abstract search backend capabilities used by services."""

    def search(
        self,
        index_type: IndexType,
        query: SearchQuery,
        *,
        facet_attributes: list[str] | None = None,
    ) -> tuple[SearchResult, FacetResult | None]:
        ...

    def get_document_by_id(self, index_type: IndexType, doc_id: int | str) -> SearchDocument | None:
        ...

    def ensure_index_and_settings(self, index_type: IndexType) -> None:
        ...

    def delete_all(self, index_type: IndexType) -> None:
        ...

    def add_documents_batch(self, index_type: IndexType, documents: list[SearchDocument]) -> None:
        ...

    def get_stats(self, index_type: IndexType) -> dict[str, Any]:
        ...

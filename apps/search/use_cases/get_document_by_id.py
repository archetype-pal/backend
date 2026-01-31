"""Use case: GetDocumentById."""

from apps.search.domain import IndexType
from apps.search.infrastructure.meilisearch_reader import MeilisearchIndexReader


class GetDocumentById:
    """Retrieve one document by id. Depends on ISearchIndexReader."""

    def __init__(self, reader: MeilisearchIndexReader | None = None):
        self._reader = reader or MeilisearchIndexReader()

    def __call__(self, index_type: IndexType, document_id: int | str) -> dict | None:
        return self._reader.get_document_by_id(index_type, document_id)

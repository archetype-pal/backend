"""Search and indexing services (Meilisearch)."""

from collections.abc import Callable
from itertools import islice
from typing import Any

from django.db import close_old_connections

from apps.search.contracts import SearchBackend, SearchDocument
from apps.search.meilisearch.reader import MeilisearchIndexReader
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult

VALID_PER_INDEX_ACTIONS = {"reindex", "clear", "clean_and_reindex"}


def resolve_index_type_segment(index_type_segment: str) -> IndexType:
    """Resolve URL segment to IndexType and raise on invalid values."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: '{index_type_segment}'.")
    return index_type


def index_type_segments() -> list[str]:
    """Return stable CLI/API index choices."""
    return [index_type.to_url_segment() for index_type in IndexType]


class SearchService:
    """Meilisearch search operations."""

    def __init__(self, reader: SearchBackend | None = None):
        self._reader = reader or MeilisearchIndexReader()

    def search(self, index_type: IndexType, query: SearchQuery) -> SearchResult:
        result, _ = self._reader.search(index_type, query, facet_attributes=None)
        return result

    def get_document(self, index_type: IndexType, doc_id: int | str) -> dict | None:
        return self._reader.get_document_by_id(index_type, doc_id)

    def get_facets(
        self,
        index_type: IndexType,
        query: SearchQuery,
        facet_attributes: list[str],
    ) -> FacetResult:
        _, facets = self._reader.search(index_type, query, facet_attributes=facet_attributes)
        if facets is None:
            return FacetResult(facet_distribution={}, facet_stats={})
        return facets


class IndexingService:
    """Meilisearch indexing operations."""

    def __init__(self, writer: MeilisearchIndexWriter | None = None):
        self._writer = writer or MeilisearchIndexWriter()

    REINDEX_BATCH_SIZE = 500

    def reindex(
        self,
        index_type: IndexType,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Load all documents for index_type from DB, replace index. Returns count indexed.

        If progress_callback is provided, it is called as progress_callback(done_count, total_count)
        during batched processing so the caller can report progress.
        """
        builder = get_registration(index_type).builder

        qs = get_queryset_for_index(index_type)
        total = qs.count()

        self._writer.ensure_index_and_settings(index_type)
        self._writer.delete_all(index_type)

        processed = 0
        it = qs.iterator(chunk_size=self.REINDEX_BATCH_SIZE)
        while True:
            batch = list(islice(it, self.REINDEX_BATCH_SIZE))
            if not batch:
                break
            close_old_connections()
            documents: list[SearchDocument] = []
            for obj in batch:
                documents.extend(builder(obj))
            self._writer.add_documents_batch(index_type, documents)
            processed += len(batch)
            if progress_callback is not None:
                progress_callback(processed, total)

        return processed

    def clear(self, index_type: IndexType) -> None:
        """Delete all documents in the index."""
        self._writer.delete_all(index_type)

    def setup_index(self, index_type: IndexType) -> None:
        """Ensure index and Meilisearch settings exist."""
        self._writer.ensure_index_and_settings(index_type)

    def get_stats(self, index_type: IndexType) -> dict:
        """Return index stats (e.g. number of documents)."""
        return self._writer.get_stats(index_type)


class SearchOrchestrationService:
    """Single place for per-index and all-index search operations."""

    def __init__(self, indexing_service: IndexingService | None = None):
        self._indexing_service = indexing_service or IndexingService()

    def clear_index(self, index_type_segment: str) -> None:
        index_type = resolve_index_type_segment(index_type_segment)
        self._indexing_service.clear(index_type)

    def reindex_index(
        self,
        index_type_segment: str,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        index_type = resolve_index_type_segment(index_type_segment)
        return self._indexing_service.reindex(index_type, progress_callback=progress_callback)

    def clear_and_reindex_index(
        self,
        index_type_segment: str,
        *,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        index_type = resolve_index_type_segment(index_type_segment)
        self._indexing_service.clear(index_type)
        return self._indexing_service.reindex(index_type, progress_callback=progress_callback)

    def reindex_all(self) -> dict[str, int]:
        indexed_per_segment: dict[str, int] = {}
        for index_type in IndexType:
            segment = index_type.to_url_segment()
            indexed_per_segment[segment] = self._indexing_service.reindex(index_type)
        return indexed_per_segment

    def setup_all_indexes(self) -> list[str]:
        segments: list[str] = []
        for index_type in IndexType:
            self._indexing_service.setup_index(index_type)
            segments.append(index_type.to_url_segment())
        return segments

    def clear_and_reindex_all(
        self,
        *,
        progress_callback: Callable[[int, int, str, int, int], None] | None = None,
    ) -> dict[str, int]:
        indexed_per_segment: dict[str, int] = {}
        total_indexes = len(IndexType)
        for index_position, index_type in enumerate(IndexType, start=1):
            segment = index_type.to_url_segment()

            def _callback(done: int, total_docs: int) -> None:
                if progress_callback is None:
                    return
                progress_callback(index_position, total_indexes, segment, done, total_docs)

            self._indexing_service.clear(index_type)
            indexed_per_segment[segment] = self._indexing_service.reindex(index_type, progress_callback=_callback)
        return indexed_per_segment

"""Search and indexing services (Meilisearch)."""

from collections.abc import Callable
from itertools import islice

from django.apps import apps
from django.db import close_old_connections

from apps.search.documents import BUILDERS
from apps.search.meilisearch.reader import MeilisearchIndexReader
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult


def get_queryset_for_index(index_type: IndexType):
    """Return the Django model queryset for the given index type."""
    model_map = {
        IndexType.ITEM_PARTS: ("manuscripts", "ItemPart"),
        IndexType.ITEM_IMAGES: ("manuscripts", "ItemImage"),
        IndexType.SCRIBES: ("scribes", "Scribe"),
        IndexType.HANDS: ("scribes", "Hand"),
        IndexType.GRAPHS: ("annotations", "Graph"),
    }
    app_label, model_name = model_map[index_type]
    model = apps.get_model(app_label, model_name)
    return model.objects.all().order_by("pk")


class SearchService:
    """Meilisearch search operations."""

    def __init__(self, reader: MeilisearchIndexReader | None = None):
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
        builder = BUILDERS.get(index_type)
        if not builder:
            raise ValueError(f"No document builder for index type {index_type}")

        qs = get_queryset_for_index(index_type)
        documents = []
        for obj in qs.iterator(chunk_size=1000):
            close_old_connections()
            doc = builder(obj)
            documents.append(doc)

        self._writer.delete_all(index_type)
        self._writer.ensure_index_and_settings(index_type)

        processed = 0
        it = qs.iterator(chunk_size=self.REINDEX_BATCH_SIZE)
        while True:
            batch = list(islice(it, self.REINDEX_BATCH_SIZE))
            if not batch:
                break
            documents = [builder(obj) for obj in batch]
            self._writer.add_documents_batch(index_type, documents)
            processed += len(documents)
            if progress_callback is not None:
                progress_callback(processed, total)

        return processed

    def clear(self, index_type: IndexType) -> None:
        """Delete all documents in the index."""
        self._writer.delete_all(index_type)

    def get_stats(self, index_type: IndexType) -> dict:
        """Return index stats (e.g. number of documents)."""
        return self._writer.get_stats(index_type)

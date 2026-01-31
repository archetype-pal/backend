"""Meilisearch implementation of IIndexWriter."""

from django.conf import settings

from apps.search.domain import IndexType
from apps.search.infrastructure.client import get_meilisearch_client
from apps.search.infrastructure.index_settings import (
    FILTERABLE_ATTRIBUTES,
    SEARCHABLE_ATTRIBUTES,
    SORTABLE_ATTRIBUTES,
)


class MeilisearchIndexWriter:
    """Implements IIndexWriter using Meilisearch SDK."""

    BATCH_SIZE = 1000
    PRIMARY_KEY = "id"

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

    def ensure_index_and_settings(self, index_type: IndexType) -> None:
        """Create index if needed and set filterable/sortable/searchable attributes."""
        uid = self._index_uid(index_type)
        try:
            self.client.get_index(uid)
        except Exception:
            self.client.create_index(uid, {"primaryKey": self.PRIMARY_KEY})

        index = self.client.index(uid)
        filterable = FILTERABLE_ATTRIBUTES.get(index_type, [])
        sortable = SORTABLE_ATTRIBUTES.get(index_type, [])
        searchable = SEARCHABLE_ATTRIBUTES.get(index_type, [])
        index.update_filterable_attributes(filterable)
        index.update_sortable_attributes(sortable)
        index.update_searchable_attributes(searchable)

    def replace_documents(self, index_type: IndexType, documents: list[dict]) -> None:
        """Replace index contents with documents. Creates index and sets settings if needed."""
        self.ensure_index_and_settings(index_type)
        uid = self._index_uid(index_type)
        index = self.client.index(uid)
        for i in range(0, len(documents), self.BATCH_SIZE):
            batch = documents[i : i + self.BATCH_SIZE]
            index.update_documents(batch, primary_key=self.PRIMARY_KEY)

    def delete_all(self, index_type: IndexType) -> None:
        """Delete all documents in the index."""
        uid = self._index_uid(index_type)
        try:
            index = self.client.index(uid)
            index.delete_all_documents()
        except Exception:
            pass

    def get_stats(self, index_type: IndexType) -> dict:
        """Return index stats (e.g. number of documents)."""
        uid = self._index_uid(index_type)
        try:
            index = self.client.index(uid)
            stats = index.get_stats()
            return {
                "numberOfDocuments": getattr(stats, "number_of_documents", stats.get("numberOfDocuments", 0)),
            }
        except Exception:
            return {"numberOfDocuments": 0}

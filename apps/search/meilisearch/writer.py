"""Meilisearch index writer."""

import logging

from django.conf import settings
from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

from apps.search.meilisearch.client import get_meilisearch_client
from apps.search.meilisearch.config import (
    FILTERABLE_ATTRIBUTES,
    SEARCHABLE_ATTRIBUTES,
    SORTABLE_ATTRIBUTES,
)
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


class MeilisearchIndexWriter:
    """Write/clear Meilisearch indexes using the SDK."""

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
        except MeilisearchApiError:
            # Index does not exist; create it
            task_info = self.client.create_index(uid, {"primaryKey": self.PRIMARY_KEY})
            self.client.wait_for_task(task_info.task_uid)
        except (MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.exception("Meilisearch connection error ensuring index %s: %s", uid, e)
            raise

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

    def add_documents_batch(self, index_type: IndexType, documents: list[dict]) -> None:
        """Add or update a batch of documents. Index must already exist (e.g. after ensure_index_and_settings)."""
        if not documents:
            return
        uid = self._index_uid(index_type)
        index = self.client.index(uid)
        index.update_documents(documents, primary_key=self.PRIMARY_KEY)

    def delete_all(self, index_type: IndexType) -> None:
        """Delete all documents in the index."""
        uid = self._index_uid(index_type)
        try:
            index = self.client.index(uid)
            task_info = index.delete_all_documents()
            self.client.wait_for_task(task_info.task_uid)
        except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.warning("Meilisearch delete_all failed for %s: %s", uid, e)
        except Exception:
            logger.exception("Unexpected error in delete_all for %s", uid)
            raise

    def _doc_count_from_stats(self, stats) -> int:
        """Extract document count from SDK IndexStats (object) or raw dict (snake_case/camelCase)."""
        if stats is None:
            return 0
        if hasattr(stats, "number_of_documents"):
            return getattr(stats, "number_of_documents", 0)
        if isinstance(stats, dict):
            return stats.get("number_of_documents", stats.get("numberOfDocuments", 0))
        return 0

    def get_stats(self, index_type: IndexType) -> dict:
        """Return index stats (e.g. number of documents)."""
        uid = self._index_uid(index_type)
        try:
            index = self.client.index(uid)
            stats = index.get_stats()
            return {"numberOfDocuments": self._doc_count_from_stats(stats)}
        except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.debug("Meilisearch get_stats failed for %s: %s", uid, e)
            return {"numberOfDocuments": 0}
        except Exception:
            logger.exception("Unexpected error in get_stats for %s", uid)
            raise

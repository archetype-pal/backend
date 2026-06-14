"""Meilisearch index writer."""

import logging
from typing import Any

from django.conf import settings
from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

from apps.search.contracts import SearchDocument
from apps.search.meilisearch.client import get_meilisearch_client
from apps.search.registry import get_registration
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


class MeilisearchIndexWriter:
    """Write/clear Meilisearch indexes using the SDK."""

    BATCH_SIZE = 1000
    PRIMARY_KEY = "id"
    BUILD_SUFFIX = "__build"
    # Meilisearch caps the reported total hit count at `maxTotalHits` (default
    # 1000), which made every category with ≥1000 records read exactly "1,000".
    # Raise it well above the corpus size so result counts are exact.
    MAX_TOTAL_HITS = 1_000_000

    def __init__(self):
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = get_meilisearch_client()
        return self._client

    def _index_uid(self, index_type: IndexType) -> str:
        prefix = getattr(settings, "MEILISEARCH_INDEX_PREFIX", "") or ""
        return f"{prefix}{index_type.uid}".strip() or index_type.uid

    def _build_uid(self, index_type: IndexType) -> str:
        """UID for the staging index used during atomic reindex (P1.3)."""
        return f"{self._index_uid(index_type)}{self.BUILD_SUFFIX}"

    def _apply_index_settings(self, index_uid: str, index_type: IndexType) -> None:
        registration = get_registration(index_type)
        index = self.client.index(index_uid)
        index.update_filterable_attributes(registration.filterable_attributes)
        index.update_sortable_attributes(registration.sortable_attributes)
        index.update_searchable_attributes(registration.searchable_attributes)
        index.update_pagination_settings({"maxTotalHits": self.MAX_TOTAL_HITS})
        # Disable typo tolerance on numbers: charter dates (1124 vs 1224) and
        # numeric shelfmark/catalogue tokens must match exactly, not fuzzily.
        index.update_typo_tolerance({"disableOnNumbers": True})

    def ensure_index_and_settings(self, index_type: IndexType) -> None:
        """Create index if needed and set filterable/sortable/searchable attributes."""
        uid = self._index_uid(index_type)
        try:
            self.client.get_index(uid)
        except MeilisearchApiError as e:
            if e.code == "index_not_found":
                task_info = self.client.create_index(uid, {"primaryKey": self.PRIMARY_KEY})
                self.client.wait_for_task(task_info.task_uid)
            else:
                raise
        except (MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.exception("Meilisearch connection error ensuring index %s: %s", uid, e)
            raise

        self._apply_index_settings(uid, index_type)

    def replace_documents(self, index_type: IndexType, documents: list[SearchDocument]) -> None:
        """Replace index contents with documents. Creates index and sets settings if needed."""
        self.ensure_index_and_settings(index_type)
        uid = self._index_uid(index_type)
        index = self.client.index(uid)
        for i in range(0, len(documents), self.BATCH_SIZE):
            batch = documents[i : i + self.BATCH_SIZE]
            index.update_documents(batch, primary_key=self.PRIMARY_KEY)

    def prepare_build_index(self, index_type: IndexType) -> None:
        """Drop any stale build index from a prior failed reindex, then create a fresh one
        with the same settings as the live index. The build index is the staging target
        for atomic reindex via swap_indexes."""
        build_uid = self._build_uid(index_type)
        self._drop_index_if_exists(build_uid)
        task_info = self.client.create_index(build_uid, {"primaryKey": self.PRIMARY_KEY})
        self.client.wait_for_task(task_info.task_uid)
        self._apply_index_settings(build_uid, index_type)

    def add_documents_to_build(self, index_type: IndexType, documents: list[SearchDocument]) -> None:
        """Write a batch into the staging build index."""
        if not documents:
            return
        build_uid = self._build_uid(index_type)
        index = self.client.index(build_uid)
        index.update_documents(documents, primary_key=self.PRIMARY_KEY)

    def swap_with_build(self, index_type: IndexType) -> None:
        """Atomically swap the live index with the build index. After this call,
        the freshly-built documents are live and the previous live contents are
        in the build index (which can then be dropped)."""
        live_uid = self._index_uid(index_type)
        build_uid = self._build_uid(index_type)
        task_info = self.client.swap_indexes([{"indexes": [live_uid, build_uid]}])
        self.client.wait_for_task(task_info.task_uid)

    def drop_build_index(self, index_type: IndexType) -> None:
        """Drop the build index. Called after swap to clean up the now-stale data."""
        self._drop_index_if_exists(self._build_uid(index_type))

    def _drop_index_if_exists(self, uid: str) -> None:
        try:
            task_info = self.client.delete_index(uid)
            self.client.wait_for_task(task_info.task_uid)
        except MeilisearchApiError as e:
            if e.code != "index_not_found":
                raise

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

    def _doc_count_from_stats(self, stats: Any) -> int:
        """Extract document count from SDK IndexStats (object) or raw dict (snake_case/camelCase)."""
        if stats is None:
            return 0
        if hasattr(stats, "number_of_documents"):
            value = getattr(stats, "number_of_documents", 0)
            return int(value) if isinstance(value, (int, float, str)) else 0
        if isinstance(stats, dict):
            value = stats.get("number_of_documents", stats.get("numberOfDocuments", 0))
            return int(value) if isinstance(value, (int, float, str)) else 0
        return 0

    def get_stats(self, index_type: IndexType) -> dict[str, int]:
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

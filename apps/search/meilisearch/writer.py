from collections.abc import Sequence
import logging

from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError, MeilisearchError

from apps.search.contracts import SearchDocument
from apps.search.meilisearch.client import MeilisearchAdapter
from apps.search.registry import get_registration
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


def _is_index_not_found(exc: MeilisearchApiError) -> bool:
    return bool(getattr(exc, "code", None) == "index_not_found")


class MeilisearchIndexWriter(MeilisearchAdapter):
    PRIMARY_KEY = "id"
    BUILD_SUFFIX = "__build"
    # Meilisearch caps reported hit counts at `maxTotalHits` (default 1000),
    # which made every category with >=1000 records read exactly "1,000".
    MAX_TOTAL_HITS = 1_000_000
    # The SDK's 5s default is routinely exceeded by a settings update or a swap
    # on a large index (graphs is ~25k docs), aborting the sync mid-reindex.
    TASK_TIMEOUT_MS = 120_000

    def _wait(self, task_uid: int, *, what: str = "") -> None:
        """Block until Meilisearch has processed the task; raise if it failed.

        Meilisearch accepts almost any request and fails it asynchronously — a
        document with the wrong primary-key type, a filter on a non-filterable
        attribute — so without this a broken write looks like a success.
        """
        task = self.client.wait_for_task(task_uid, timeout_in_ms=self.TASK_TIMEOUT_MS)
        if getattr(task, "status", None) == "failed":
            code = (getattr(task, "error", None) or {}).get("code")
            raise MeilisearchError(f"Meilisearch task failed{f' ({what})' if what else ''}: {code}")

    def _build_uid(self, index_type: IndexType) -> str:
        """UID for the staging index used during an atomic reindex."""
        return f"{self._index_uid(index_type)}{self.BUILD_SUFFIX}"

    def _apply_index_settings(self, index_uid: str, index_type: IndexType) -> None:
        registration = get_registration(index_type)
        index = self.client.index(index_uid)
        tasks = [
            index.update_filterable_attributes(registration.filterable_attributes),
            index.update_sortable_attributes(registration.sortable_attributes),
            index.update_searchable_attributes(registration.searchable_attributes),
            index.update_pagination_settings({"maxTotalHits": self.MAX_TOTAL_HITS}),
            # Charter dates (1124 vs 1224) must match exactly, not fuzzily.
            index.update_typo_tolerance({"disableOnNumbers": True}),
        ]
        # Tasks for one index run in order, so awaiting the last settings task
        # awaits them all — settings must land before documents or a swap.
        self._wait(tasks[-1].task_uid)

    def ensure_index_and_settings(self, index_type: IndexType) -> None:
        uid = self._index_uid(index_type)
        try:
            self.client.get_index(uid)
        except MeilisearchApiError as e:
            if _is_index_not_found(e):
                task_info = self.client.create_index(uid, {"primaryKey": self.PRIMARY_KEY})
                self._wait(task_info.task_uid)
            else:
                raise
        except (MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.exception("Meilisearch connection error ensuring index %s: %s", uid, e)
            raise

        self._apply_index_settings(uid, index_type)

    def update_documents(self, index_type: IndexType, documents: Sequence[SearchDocument]) -> None:
        """Incremental write: waits for the task so a rejected document surfaces in the sync task."""
        if not documents:
            return
        uid = self._index_uid(index_type)
        try:
            task_info = self.client.index(uid).update_documents(list(documents), primary_key=self.PRIMARY_KEY)
        except MeilisearchApiError as e:
            if not _is_index_not_found(e):
                raise
            self.ensure_index_and_settings(index_type)
            task_info = self.client.index(uid).update_documents(list(documents), primary_key=self.PRIMARY_KEY)
        self._wait(task_info.task_uid, what=f"update {len(documents)} documents on {uid}")

    def delete_documents(self, index_type: IndexType, document_ids: Sequence[int | str]) -> None:
        if not document_ids:
            return
        uid = self._index_uid(index_type)
        try:
            task_info = self.client.index(uid).delete_documents([str(doc_id) for doc_id in document_ids])
        except MeilisearchApiError as e:
            if _is_index_not_found(e):
                return
            raise
        self._wait(task_info.task_uid, what=f"delete {len(document_ids)} documents on {uid}")

    def delete_documents_by_filter(self, index_type: IndexType, filter_expression: str) -> None:
        """Delete every document matching a filter.

        Needed where the document id is derived from the row rather than equal
        to its pk (see `IndexRegistration.parent_id_field`), which makes
        `delete_documents` unable to address them.

        """
        if not filter_expression:
            return
        uid = self._index_uid(index_type)
        try:
            task_info = self.client.index(uid).delete_documents(filter=filter_expression)
        except MeilisearchApiError as e:
            if _is_index_not_found(e):
                return
            raise
        self._wait(
            task_info.task_uid,
            what=f"filtered delete on {uid}; if the attribute is not filterable yet, run setup-search-indexes",
        )

    def prepare_build_index(self, index_type: IndexType) -> None:
        """Drop any stale build index from a prior failed reindex, then create a fresh one
        with the same settings as the live index. The build index is the staging target
        for atomic reindex via swap_indexes."""
        build_uid = self._build_uid(index_type)
        self._drop_index_if_exists(build_uid)
        task_info = self.client.create_index(build_uid, {"primaryKey": self.PRIMARY_KEY})
        self._wait(task_info.task_uid)
        self._apply_index_settings(build_uid, index_type)

    def add_documents_to_build(self, index_type: IndexType, documents: list[SearchDocument]) -> None:
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
        self._wait(task_info.task_uid)

    def drop_build_index(self, index_type: IndexType) -> None:
        self._drop_index_if_exists(self._build_uid(index_type))

    def _drop_index_if_exists(self, uid: str) -> None:
        try:
            task_info = self.client.delete_index(uid)
            self._wait(task_info.task_uid)
        except MeilisearchApiError as e:
            if e.code != "index_not_found":
                raise

    def delete_all(self, index_type: IndexType) -> None:
        uid = self._index_uid(index_type)
        try:
            index = self.client.index(uid)
            task_info = index.delete_all_documents()
            self._wait(task_info.task_uid)
        except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.warning("Meilisearch delete_all failed for %s: %s", uid, e)
            raise
        except Exception:
            logger.exception("Unexpected error in delete_all for %s", uid)
            raise

    def get_stats(self, index_type: IndexType) -> dict[str, int]:
        uid = self._index_uid(index_type)
        try:
            stats = self.client.index(uid).get_stats()
            return {"numberOfDocuments": int(getattr(stats, "number_of_documents", 0) or 0)}
        except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError) as e:
            logger.debug("Meilisearch get_stats failed for %s: %s", uid, e)
            return {"numberOfDocuments": 0}
        except Exception:
            logger.exception("Unexpected error in get_stats for %s", uid)
            raise

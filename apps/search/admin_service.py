"""Backoffice search management: index stats, starting tasks, reading task state."""

import logging
from typing import Any

from celery.result import AsyncResult
from django.core.cache import cache

from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.services import IndexingService
from apps.search.types import IndexType

logger = logging.getLogger(__name__)

# `clean_and_reindex` and `clear_and_rebuild_all` are kept as accepted action
# names for existing clients; they were never different from a reindex
# (`IndexingService.reindex` builds into a staging index and swaps it in, so a
# pre-clear would only open a window of zero results).
PER_INDEX_ACTIONS = {"reindex", "clear", "clean_and_reindex"}
ALL_INDEX_ACTIONS = {"reindex_all", "clear_and_rebuild_all"}
ACTIONS = PER_INDEX_ACTIONS | ALL_INDEX_ACTIONS


# The fan-out indexes count documents by parsing every text; the dashboard polls this.
_COUNT_CACHE_SECONDS = 60


def expected_document_count(index_type: IndexType) -> int:
    """How many documents the database would produce for the index, for the in-sync check."""
    registration = get_registration(index_type)
    queryset = get_queryset_for_index(index_type)
    if registration.documents_per_row is None:
        return int(queryset.count())
    key = f"search:expected-count:{index_type}"
    if (cached := cache.get(key)) is not None:
        return int(cached)
    # Counting needs the content only; drop the builder's joins (`only()` cannot defer a select_related field).
    rows = (
        queryset.select_related(None)
        .prefetch_related(None)
        .only("id", "content")
        .iterator(chunk_size=IndexingService.REINDEX_BATCH_SIZE)
    )
    count = sum(registration.documents_per_row(obj) for obj in rows)
    cache.set(key, count, _COUNT_CACHE_SECONDS)
    return count


class SearchAdminService:
    def get_index_stats_list(self) -> list[dict[str, Any]]:
        writer = MeilisearchIndexWriter()
        result: list[dict[str, Any]] = []
        for index_type in IndexType:
            meilisearch_count = writer.get_stats(index_type).get("numberOfDocuments", 0)
            try:
                db_count = expected_document_count(index_type)
            except Exception:
                logger.warning("Failed to compute expected db count for %s", index_type.segment, exc_info=True)
                db_count = 0
            result.append(
                {
                    "index_type": index_type.segment,
                    "uid": index_type.value,
                    "label": index_type.segment.replace("-", " ").title(),
                    "meilisearch_count": meilisearch_count,
                    "db_count": db_count,
                    "in_sync": meilisearch_count == db_count,
                }
            )
        return result

    def start_action(self, action: str, index_type: str | None) -> dict[str, Any]:
        """Queue *action*; `SearchActionSerializer` has already checked the names, so a bad one here is a bug."""
        from apps.search.tasks import clear_search_index, reindex_all_search_indexes, reindex_search_index

        if action in PER_INDEX_ACTIONS:
            if not index_type:
                raise ValueError(f"'index_type' is required for action '{action}'.")
            task_fn = clear_search_index if action == "clear" else reindex_search_index
            task: AsyncResult[Any] = task_fn.delay(index_type)
            return {"task_id": task.id, "message": f"Task '{action}' started for {index_type}."}

        if action == "reindex_all":
            task_ids = [reindex_search_index.delay(idx.segment).id for idx in IndexType]
            return {"task_ids": task_ids, "message": "Reindex started for all indexes."}

        if action == "clear_and_rebuild_all":
            task = reindex_all_search_indexes.delay()
            return {"task_id": task.id, "message": "Reindex of all indexes started."}

        raise ValueError(f"Unknown action '{action}'.")

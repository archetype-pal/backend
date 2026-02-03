"""Celery tasks for search index management (Meilisearch)."""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from apps.search.services import IndexingService
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


def _resolve_index_type(index_type_segment: str) -> IndexType:
    """Resolve URL segment to IndexType. Raises ValueError if unknown."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: {index_type_segment}")
    return index_type


def _progress_meta(
    current: int,
    total: int,
    message: str,
    *,
    index_done: int = 0,
    index_total: int = 0,
) -> dict[str, Any]:
    """Build meta dict for task progress (used by admin status polling)."""
    return {
        "current": current,
        "total": total,
        "message": message,
        "index_done": index_done,
        "index_total": index_total,
    }


def _make_single_index_progress_callback(task: Task, segment: str):
    """Return a progress_callback(done, total) for a single-index reindex task."""

    def progress_callback(done: int, total: int) -> None:
        task.update_state(
            state="PROGRESS",
            meta=_progress_meta(
                1,
                1,
                f"Reindexing {segment}… {done}/{total} docs",
                index_done=done,
                index_total=total,
            ),
        )

    return progress_callback


@shared_task(bind=True)
def reindex_search_index(self: Task, index_type_segment: str) -> dict[str, Any]:
    """Reindex a single search index (add/update from DB)."""
    index_type = _resolve_index_type(index_type_segment)
    self.update_state(
        state="STARTED",
        meta=_progress_meta(1, 1, f"Reindexing {index_type_segment}…"),
    )
    callback = _make_single_index_progress_callback(self, index_type_segment)

    service = IndexingService()
    count = service.reindex(index_type, progress_callback=callback)

    logger.info("Reindexed search index %s: %d documents.", index_type_segment, count)
    return {"action": "reindex", "index_type": index_type_segment, "indexed": count}


@shared_task
def clear_search_index(index_type_segment: str) -> dict[str, Any]:
    """Clear a search index (remove all documents)."""
    index_type = _resolve_index_type(index_type_segment)

    service = IndexingService()
    service.clear(index_type)

    logger.info("Cleared search index %s.", index_type_segment)
    return {"action": "clear", "index_type": index_type_segment}


@shared_task(bind=True)
def clean_and_reindex_search_index(self: Task, index_type_segment: str) -> dict[str, Any]:
    """Clear then reindex a single search index."""
    index_type = _resolve_index_type(index_type_segment)
    self.update_state(
        state="STARTED",
        meta=_progress_meta(1, 1, f"Clearing and reindexing {index_type_segment}…"),
    )
    callback = _make_single_index_progress_callback(self, index_type_segment)

    service = IndexingService()
    service.clear(index_type)
    count = service.reindex(index_type, progress_callback=callback)

    logger.info("Cleaned and reindexed search index %s: %d documents.", index_type_segment, count)
    return {
        "action": "clean_and_reindex",
        "index_type": index_type_segment,
        "indexed": count,
    }


@shared_task(bind=True)
def clear_and_reindex_all_search_indexes(self: Task) -> dict[str, Any]:
    """Clear all indexes then reindex all (admin 'Clear & Rebuild all')."""
    index_types = list(IndexType)
    n = len(index_types)

    self.update_state(
        state="STARTED",
        meta=_progress_meta(0, n, "Clear and reindex all started."),
    )

    service = IndexingService()
    total_indexed = 0

    for i, index_type in enumerate(index_types):
        segment = index_type.to_url_segment()

        def make_callback(idx: int, seg: str):
            def progress_callback(done: int, index_total: int) -> None:
                self.update_state(
                    state="PROGRESS",
                    meta=_progress_meta(
                        idx + 1,
                        n,
                        f"Reindexing {seg}… {done}/{index_total} docs",
                        index_done=done,
                        index_total=index_total,
                    ),
                )

            return progress_callback

        service.clear(index_type)
        count = service.reindex(index_type, progress_callback=make_callback(i, segment))
        total_indexed += count

        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(
                i + 1,
                n,
                f"Reindexing {segment}… done",
                index_done=count,
                index_total=count,
            ),
        )
        logger.info("Cleared and reindexed %s: %d documents.", segment, count)

    return {"action": "clear_and_reindex_all", "indexed": total_indexed}

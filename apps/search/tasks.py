"""Celery tasks for search index management (Meilisearch)."""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from apps.search.services import SearchOrchestrationService, resolve_index_type_segment
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


def _progress_meta(
    current: int,
    total: int,
    message: str,
    *,
    index_done: int = 0,
    index_total: int = 0,
) -> dict[str, Any]:
    """Build meta dict for task progress (used by management status polling)."""
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


def _run_single_index_task(
    task: Task,
    *,
    action: str,
    segment: str,
    started_message: str,
    operation,
) -> dict[str, Any]:
    """Shared skeleton for single-index task progress and result payload."""
    resolve_index_type_segment(segment)
    task.update_state(
        state="STARTED",
        meta=_progress_meta(1, 1, started_message),
    )
    callback = _make_single_index_progress_callback(task, segment)
    count = operation(segment, progress_callback=callback)
    return {"action": action, "index_type": segment, "indexed": count}


@shared_task(bind=True)
def reindex_search_index(self: Task, index_type_segment: str) -> dict[str, Any]:
    """Reindex a single search index (add/update from DB)."""
    payload = _run_single_index_task(
        self,
        action="reindex",
        segment=index_type_segment,
        started_message=f"Reindexing {index_type_segment}…",
        operation=SearchOrchestrationService().reindex_index,
    )
    logger.info("Reindexed search index %s: %d documents.", index_type_segment, payload["indexed"])
    return payload


@shared_task
def clear_search_index(index_type_segment: str) -> dict[str, Any]:
    """Clear a search index (remove all documents)."""
    resolve_index_type_segment(index_type_segment)
    SearchOrchestrationService().clear_index(index_type_segment)

    logger.info("Cleared search index %s.", index_type_segment)
    return {"action": "clear", "index_type": index_type_segment}


@shared_task(bind=True)
def clean_and_reindex_search_index(self: Task, index_type_segment: str) -> dict[str, Any]:
    """Clear then reindex a single search index."""
    payload = _run_single_index_task(
        self,
        action="clean_and_reindex",
        segment=index_type_segment,
        started_message=f"Clearing and reindexing {index_type_segment}…",
        operation=SearchOrchestrationService().clear_and_reindex_index,
    )
    logger.info("Cleaned and reindexed search index %s: %d documents.", index_type_segment, payload["indexed"])
    return payload


@shared_task(bind=True)
def clear_and_reindex_all_search_indexes(self: Task) -> dict[str, Any]:
    """Clear all indexes then reindex all (management 'Clear & Rebuild all')."""
    total_indexes = len(IndexType)
    orchestration = SearchOrchestrationService()

    self.update_state(
        state="STARTED",
        meta=_progress_meta(0, total_indexes, "Clear and reindex all started."),
    )

    def progress_callback(index_pos: int, index_total: int, segment: str, done: int, docs_total: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(
                index_pos,
                index_total,
                f"Reindexing {segment}… {done}/{docs_total} docs",
                index_done=done,
                index_total=docs_total,
            ),
        )

    indexed_per_segment = orchestration.clear_and_reindex_all(progress_callback=progress_callback)
    for segment, count in indexed_per_segment.items():
        logger.info("Cleared and reindexed %s: %d documents.", segment, count)

    return {"action": "clear_and_reindex_all", "indexed": sum(indexed_per_segment.values())}

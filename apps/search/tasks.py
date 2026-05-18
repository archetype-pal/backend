"""Celery tasks for search index management (Meilisearch)."""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from apps.search.progress import CeleryTaskReporter
from apps.search.services import SearchOrchestrationService, resolve_index_type_segment

logger = logging.getLogger(__name__)


def _run_single_index_task(
    task: Task,
    *,
    action: str,
    segment: str,
    started_message: str,
    operation,
) -> dict[str, Any]:
    """Shared skeleton for single-index task progress and result payload.

    A single `CeleryTaskReporter` owns the `update_state` calls; the
    orchestration service calls into it (no closures threaded down the
    stack)."""
    resolve_index_type_segment(segment)
    reporter = CeleryTaskReporter(task)
    reporter.start(started_message)
    # Single-index runs have a degenerate outer loop (1 of 1); priming the
    # reporter once means batch reports carry the right segment label.
    reporter.advance_to(1, 1, segment)
    count = operation(segment, reporter=reporter)
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
    reporter = CeleryTaskReporter(self)
    reporter.start("Clear and reindex all started.")
    indexed_per_segment = SearchOrchestrationService().clear_and_reindex_all(reporter=reporter)
    for segment, count in indexed_per_segment.items():
        logger.info("Cleared and reindexed %s: %d documents.", segment, count)

    return {"action": "clear_and_reindex_all", "indexed": sum(indexed_per_segment.values())}

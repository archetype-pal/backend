import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task
from meilisearch.errors import MeilisearchCommunicationError

from apps.search.progress import CeleryTaskReporter
from apps.search.services import IndexingService, SearchOrchestrationService, resolve_index_type_segment

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def reindex_search_index(self: Task, index_type_segment: str) -> dict[str, Any]:
    """Rebuild one index from the database (atomic build-and-swap, see IndexingService).

    A single `CeleryTaskReporter` owns the `update_state` calls; the
    orchestration service calls into it (no closures threaded down the stack).
    """
    resolve_index_type_segment(index_type_segment)
    reporter = CeleryTaskReporter(self)
    reporter.start(f"Reindexing {index_type_segment}…")
    # Priming the 1-of-1 outer loop makes batch reports carry the segment label.
    reporter.advance_to(1, 1, index_type_segment)
    count = SearchOrchestrationService().reindex_index(index_type_segment, reporter=reporter)
    logger.info("Reindexed search index %s: %d documents.", index_type_segment, count)
    return {"action": "reindex", "index_type": index_type_segment, "indexed": count}


@shared_task
def clear_search_index(index_type_segment: str) -> dict[str, Any]:
    resolve_index_type_segment(index_type_segment)
    SearchOrchestrationService().clear_index(index_type_segment)

    logger.info("Cleared search index %s.", index_type_segment)
    return {"action": "clear", "index_type": index_type_segment}


@shared_task(bind=True)
def reindex_all_search_indexes(self: Task) -> dict[str, Any]:
    """Rebuild every index in one task, index by index, with progress."""
    reporter = CeleryTaskReporter(self)
    reporter.start("Reindex all started.")
    indexed_per_segment = SearchOrchestrationService().reindex_all(reporter=reporter)
    for segment, count in indexed_per_segment.items():
        logger.info("Reindexed %s: %d documents.", segment, count)

    return {"action": "reindex_all", "indexed": sum(indexed_per_segment.values())}


_INCREMENTAL_RETRY_KWARGS: dict[str, Any] = {
    "autoretry_for": (MeilisearchCommunicationError, ConnectionError, OSError),
    "max_retries": 3,
    "retry_backoff": True,
    "retry_backoff_max": 60,
    "retry_jitter": True,
}


@shared_task(**_INCREMENTAL_RETRY_KWARGS)
def sync_search_documents(index_type_segment: str, pks: list[int]) -> dict[str, Any]:
    index_type = resolve_index_type_segment(index_type_segment)
    indexed = IndexingService().update_documents_by_ids(index_type, pks)
    logger.info("Incrementally synced %d documents for search index %s (pks=%s).", indexed, index_type_segment, pks)
    return {"action": "sync_documents", "index_type": index_type_segment, "indexed": indexed, "pks": pks}


@shared_task(**_INCREMENTAL_RETRY_KWARGS)
def delete_search_documents(index_type_segment: str, pks: list[int]) -> dict[str, Any]:
    index_type = resolve_index_type_segment(index_type_segment)
    IndexingService().delete_documents_by_ids(index_type, pks)
    logger.info("Incrementally deleted documents for search index %s (pks=%s).", index_type_segment, pks)
    return {"action": "delete_documents", "index_type": index_type_segment, "pks": pks}

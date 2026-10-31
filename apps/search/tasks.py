"""Celery entry points. Index types travel as URL segments (`item-parts`), the form the API and CLI use."""

import logging
from typing import Any

from celery import shared_task
from celery.app.task import Task

from apps.search.meilisearch.client import MEILI_UNAVAILABLE
from apps.search.progress import CeleryTaskReporter
from apps.search.services import IndexingService
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def reindex_search_index(self: Task, segment: str) -> dict[str, Any]:
    """Rebuild one index from the database (atomic build-and-swap, see IndexingService)."""
    index_type = IndexType.from_segment(segment)
    reporter = CeleryTaskReporter(self)
    reporter.start(f"Reindexing {segment}…")
    # Priming the 1-of-1 outer loop makes batch reports carry the segment label.
    reporter.advance_to(1, 1, segment)
    count = IndexingService().reindex(index_type, reporter=reporter)
    logger.info("Reindexed search index %s: %d documents.", segment, count)
    return {"action": "reindex", "index_type": segment, "indexed": count}


@shared_task
def clear_search_index(segment: str) -> dict[str, Any]:
    IndexingService().clear(IndexType.from_segment(segment))
    logger.info("Cleared search index %s.", segment)
    return {"action": "clear", "index_type": segment}


@shared_task(bind=True)
def reindex_all_search_indexes(self: Task) -> dict[str, Any]:
    """Rebuild every index in one task, index by index, with progress."""
    reporter = CeleryTaskReporter(self)
    reporter.start("Reindex all started.")
    indexed = IndexingService().reindex_all(reporter=reporter)
    for segment, count in indexed.items():
        logger.info("Reindexed %s: %d documents.", segment, count)
    return {"action": "reindex_all", "indexed": sum(indexed.values())}


_INCREMENTAL_RETRY_KWARGS: dict[str, Any] = {
    "autoretry_for": MEILI_UNAVAILABLE,
    "max_retries": 3,
    "retry_backoff": True,
    "retry_backoff_max": 60,
    "retry_jitter": True,
}


@shared_task(**_INCREMENTAL_RETRY_KWARGS)
def sync_search_documents(segment: str, pks: list[int]) -> dict[str, Any]:
    indexed = IndexingService().update_documents_by_ids(IndexType.from_segment(segment), pks)
    logger.info("Incrementally synced %d documents for search index %s (%d rows).", indexed, segment, len(pks))
    return {"action": "sync_documents", "index_type": segment, "indexed": indexed, "pks": pks}


@shared_task(**_INCREMENTAL_RETRY_KWARGS)
def delete_search_documents(segment: str, pks: list[int]) -> dict[str, Any]:
    IndexingService().delete_documents_by_ids(IndexType.from_segment(segment), pks)
    logger.info("Incrementally deleted %d documents from search index %s.", len(pks), segment)
    return {"action": "delete_documents", "index_type": segment, "pks": pks}

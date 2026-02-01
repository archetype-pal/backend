"""Celery tasks for search index management (Meilisearch)."""

import logging

from celery import shared_task

from apps.search.services import IndexingService
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def reindex_search_index(self, index_type_segment: str):
    """Reindex a search index. index_type_segment: e.g. 'item-parts', 'scribes'."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: {index_type_segment}")

    service = IndexingService()
    count = service.reindex(index_type)
    logger.info("Reindexed search index %s: %d documents.", index_type_segment, count)
    return {"action": "reindex", "index_type": index_type_segment, "indexed": count}


@shared_task
def clear_search_index(index_type_segment: str):
    """Clear a search index. index_type_segment: e.g. 'item-parts'."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: {index_type_segment}")

    service = IndexingService()
    service.clear(index_type)
    logger.info("Cleared search index %s.", index_type_segment)
    return {"action": "clear", "index_type": index_type_segment}


@shared_task(bind=True)
def clean_and_reindex_search_index(self, index_type_segment: str):
    """Clear then reindex a search index. Returns combined result."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: {index_type_segment}")

    service = IndexingService()
    service.clear(index_type)
    count = service.reindex(index_type)
    logger.info("Cleaned and reindexed search index %s: %d documents.", index_type_segment, count)
    return {
        "action": "clean_and_reindex",
        "index_type": index_type_segment,
        "indexed": count,
    }


@shared_task(bind=True)
def clear_and_reindex_all_search_indexes(self):
    """Clear all indexes then reindex all. For admin 'Clear & Rebuild all'."""
    index_types = list(IndexType)
    n = len(index_types)
    self.update_state(state="STARTED", meta={"message": "Clear and reindex all started.", "total": n, "current": 0})

    service = IndexingService()
    total = 0
    for i, index_type in enumerate(index_types):
        service.clear(index_type)
        count = service.reindex(index_type)
        total += count
        self.update_state(
            state="PROGRESS",
            meta={"current": i + 1, "total": n, "message": f"Reindexing {index_type.to_url_segment()}…"},
        )
        logger.info("Cleared and reindexed %s: %d documents.", index_type.to_url_segment(), count)
    return {"action": "clear_and_reindex_all", "indexed": total}

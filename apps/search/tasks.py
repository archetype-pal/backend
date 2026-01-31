"""Celery tasks for search index management (Meilisearch)."""

import logging

from celery import shared_task

from apps.search.domain import IndexType
from apps.search.infrastructure.meilisearch_writer import MeilisearchIndexWriter
from apps.search.use_cases import ReindexIndex

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def reindex_search_index(self, index_type_segment: str):
    """Reindex a search index. index_type_segment: e.g. 'item-parts', 'scribes'."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: {index_type_segment}")

    use_case = ReindexIndex()
    count = use_case(index_type)
    logger.info("Reindexed search index %s: %d documents.", index_type_segment, count)
    return {"action": "reindex", "index_type": index_type_segment, "indexed": count}


@shared_task
def clear_search_index(index_type_segment: str):
    """Clear a search index. index_type_segment: e.g. 'item-parts'."""
    index_type = IndexType.from_url_segment(index_type_segment)
    if index_type is None:
        raise ValueError(f"Unknown index type: {index_type_segment}")

    writer = MeilisearchIndexWriter()
    writer.delete_all(index_type)
    logger.info("Cleared search index %s.", index_type_segment)
    return {"action": "clear", "index_type": index_type_segment}


@shared_task(bind=True)
def clean_and_reindex_search_index(self, index_type_segment: str):
    """Clear then reindex a search index. Returns combined result."""
    clear_search_index(index_type_segment)
    result = reindex_search_index.apply(args=[index_type_segment]).get()
    return {
        "action": "clean_and_reindex",
        "index_type": index_type_segment,
        "indexed": result.get("indexed", 0),
    }


@shared_task(bind=True)
def clear_and_reindex_all_search_indexes(self):
    """Clear all indexes then reindex all. For admin 'Clear & Rebuild all'."""
    for index_type in IndexType:
        clear_search_index(index_type.to_url_segment())
    total = 0
    for index_type in IndexType:
        result = reindex_search_index.apply(args=[index_type.to_url_segment()]).get()
        total += result.get("indexed", 0)
    return {"action": "clear_and_reindex_all", "indexed": total}

"""Admin API views for search engine / Meilisearch index management."""

import logging

from celery.result import AsyncResult
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.common.api.permissions import IsAdminUser
from apps.search.meilisearch.client import get_meilisearch_client
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.services import get_queryset_for_index
from apps.search.tasks import (
    clean_and_reindex_search_index,
    clear_and_reindex_all_search_indexes,
    clear_search_index,
    reindex_search_index,
)
from apps.search.types import IndexType

logger = logging.getLogger(__name__)

VALID_PER_INDEX_ACTIONS = {"reindex", "clear", "clean_and_reindex"}
VALID_GLOBAL_ACTIONS = {"reindex_all", "clear_and_rebuild_all"}


def _check_meilisearch_health() -> bool:
    """Return True if Meilisearch is reachable."""
    try:
        from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

        client = get_meilisearch_client()
        client.health()
        return True
    except (MeilisearchApiError, MeilisearchCommunicationError) as e:
        logger.debug("Meilisearch health check failed (API/communication): %s", e)
        return False
    except (OSError, ConnectionError) as e:
        logger.debug("Meilisearch health check failed (connection): %s", e)
        return False
    except Exception as e:
        logger.warning("Meilisearch health check failed: %s", e)
        return False


def _get_index_stats_list() -> list[dict]:
    """Gather per-index stats (Meilisearch count vs DB count)."""
    result = []
    writer = MeilisearchIndexWriter()
    for index_type in IndexType:
        segment = index_type.to_url_segment()
        stats = writer.get_stats(index_type)
        meilisearch_count = stats.get("numberOfDocuments", 0)
        try:
            qs = get_queryset_for_index(index_type)
            db_count = qs.count()
        except Exception as e:
            logger.debug("Failed to get DB count for index %s: %s", segment, e)
            db_count = 0
        result.append(
            {
                "index_type": segment,
                "uid": index_type.uid,
                "label": segment.replace("-", " ").title(),
                "meilisearch_count": meilisearch_count,
                "db_count": db_count,
                "in_sync": meilisearch_count == db_count,
            }
        )
    return result


@api_view(["GET"])
@permission_classes([IsAdminUser])
def search_stats(request):
    """GET /api/v1/admin/search/stats/ — per-index stats + health."""
    healthy = _check_meilisearch_health()

    if not healthy:
        return Response(
            {
                "healthy": False,
                "total_meilisearch": 0,
                "total_database": 0,
                "indexes": [],
            }
        )

    try:
        indexes = _get_index_stats_list()
    except Exception as exc:
        logger.exception("Failed to gather search index stats")
        return Response(
            {"healthy": False, "total_meilisearch": 0, "total_database": 0, "indexes": [], "error": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    total_ms = sum(idx["meilisearch_count"] for idx in indexes)
    total_db = sum(idx["db_count"] for idx in indexes)

    return Response(
        {
            "healthy": True,
            "total_meilisearch": total_ms,
            "total_database": total_db,
            "indexes": indexes,
        }
    )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def search_action(request):
    """POST /api/v1/admin/search/actions/ — dispatch an indexing Celery task."""
    action = request.data.get("action")
    index_type_segment = request.data.get("index_type")

    if not action:
        return Response({"detail": "Missing 'action' field."}, status=status.HTTP_400_BAD_REQUEST)

    # --- per-index actions ---
    if action in VALID_PER_INDEX_ACTIONS:
        if not index_type_segment:
            return Response(
                {"detail": f"'index_type' is required for action '{action}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Validate the index_type segment
        if IndexType.from_url_segment(index_type_segment) is None:
            return Response(
                {"detail": f"Unknown index type: '{index_type_segment}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_map = {
            "reindex": reindex_search_index,
            "clear": clear_search_index,
            "clean_and_reindex": clean_and_reindex_search_index,
        }
        task = task_map[action].delay(index_type_segment)
        return Response({"task_id": task.id, "message": f"Task '{action}' started for {index_type_segment}."})

    # --- global actions ---
    if action == "reindex_all":
        task_ids = []
        for idx_type in IndexType:
            t = reindex_search_index.delay(idx_type.to_url_segment())
            task_ids.append(t.id)
        return Response({"task_ids": task_ids, "message": "Reindex started for all indexes."})

    if action == "clear_and_rebuild_all":
        task = clear_and_reindex_all_search_indexes.delay()
        return Response({"task_id": task.id, "message": "Clear & rebuild all started."})

    return Response({"detail": f"Unknown action '{action}'."}, status=status.HTTP_400_BAD_REQUEST)


def _format_task_error(result):
    """Extract a readable error message from a failed Celery task result."""
    if result is None:
        return "Unknown error"
    if isinstance(result, BaseException):
        return str(result) or type(result).__name__
    if isinstance(result, dict):
        msg = result.get("exc_message") or result.get("message") or result.get("error")
        if isinstance(msg, (list, tuple)):
            msg = " ".join(str(m) for m in msg)
        exc_type = result.get("exc_type", "")
        if msg and exc_type:
            return f"{exc_type}: {msg}"
        return str(msg) if msg else str(result)
    return str(result)


def _safe_task_result(result: AsyncResult):
    """Get task result/exception without re-raising. Returns (result_value, error_message)."""
    if not result.ready():
        return (None, None)
    try:
        raw = result.get(propagate=False)
        if result.successful():
            return (raw, None)
        return (None, _format_task_error(raw))
    except Exception as e:
        logger.debug("Could not retrieve Celery task result: %s", e)
        return (None, str(e) or "Could not retrieve task result.")


@api_view(["GET"])
@permission_classes([IsAdminUser])
def search_task_status(request, task_id):
    """GET /api/v1/admin/search/tasks/<task_id>/ — poll Celery task status."""
    result = AsyncResult(task_id)
    state = result.state
    info = {"task_id": task_id, "state": state, "progress": None, "result": None, "error": None}

    try:
        if state in ("PROGRESS", "STARTED") and result.info:
            info["progress"] = result.info
        elif state == "SUCCESS":
            res, _ = _safe_task_result(result)
            if res is not None:
                info["result"] = res
        elif state == "FAILURE":
            _, err = _safe_task_result(result)
            info["error"] = err or "Task failed."
    except Exception as e:
        logger.warning("Failed to retrieve task status for %s: %s", task_id, e)
        info["state"] = "FAILURE"
        info["error"] = str(e) or "Failed to retrieve task status."

    return Response(info)

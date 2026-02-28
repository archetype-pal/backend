"""Application service for search management operations."""

import logging
from typing import Any

from celery.result import AsyncResult

from apps.search.meilisearch.client import get_meilisearch_client
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.registry import get_queryset_for_index
from apps.search.services import (
    VALID_PER_INDEX_ACTIONS,
    SearchOrchestrationService,
    resolve_index_type_segment,
)
from apps.search.types import IndexType

logger = logging.getLogger(__name__)


class SearchAdminService:
    """Orchestrate search admin stats and actions."""

    def check_meilisearch_health(self) -> bool:
        try:
            from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

            client = get_meilisearch_client()
            client.health()
            return True
        except (MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError):
            return False
        except Exception as exc:
            logger.warning("Meilisearch health check failed: %s", exc)
            return False

    def get_index_stats_list(self) -> list[dict[str, Any]]:
        writer = MeilisearchIndexWriter()
        result = []
        for index_type in IndexType:
            segment = index_type.to_url_segment()
            stats = writer.get_stats(index_type)
            meilisearch_count = stats.get("numberOfDocuments", 0)
            try:
                db_count = get_queryset_for_index(index_type).count()
            except Exception:
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

    def resolve_index_type(self, index_type_segment: str) -> IndexType:
        return resolve_index_type_segment(index_type_segment)

    def clear_index(self, index_type_segment: str) -> None:
        SearchOrchestrationService().clear_index(index_type_segment)

    def reindex_index(self, index_type_segment: str, *, progress_callback=None) -> int:
        return SearchOrchestrationService().reindex_index(index_type_segment, progress_callback=progress_callback)

    def clear_and_reindex_index(self, index_type_segment: str, *, progress_callback=None) -> int:
        return SearchOrchestrationService().clear_and_reindex_index(
            index_type_segment,
            progress_callback=progress_callback,
        )

    def start_action(self, action: str, index_type_segment: str | None) -> dict[str, Any]:
        from apps.search.tasks import (
            clean_and_reindex_search_index,
            clear_and_reindex_all_search_indexes,
            clear_search_index,
            reindex_search_index,
        )

        if action in VALID_PER_INDEX_ACTIONS:
            if not index_type_segment:
                raise ValueError(f"'index_type' is required for action '{action}'.")
            resolve_index_type_segment(index_type_segment)

            task_map = {
                "reindex": reindex_search_index,
                "clear": clear_search_index,
                "clean_and_reindex": clean_and_reindex_search_index,
            }
            task = task_map[action].delay(index_type_segment)
            return {"task_id": task.id, "message": f"Task '{action}' started for {index_type_segment}."}

        if action == "reindex_all":
            task_ids = [reindex_search_index.delay(idx.to_url_segment()).id for idx in IndexType]
            return {"task_ids": task_ids, "message": "Reindex started for all indexes."}

        if action == "clear_and_rebuild_all":
            task = clear_and_reindex_all_search_indexes.delay()
            return {"task_id": task.id, "message": "Clear & rebuild all started."}

        raise ValueError(f"Unknown action '{action}'.")

    def task_status(self, task_id: str) -> dict[str, Any]:
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
        except Exception as exc:
            info["state"] = "FAILURE"
            info["error"] = str(exc) or "Failed to retrieve task status."
        return info


def _format_task_error(result: Any) -> str:
    if result is None:
        return "Unknown error"
    if isinstance(result, BaseException):
        return str(result) or type(result).__name__
    if isinstance(result, dict):
        msg = result.get("exc_message") or result.get("message") or result.get("error")
        if isinstance(msg, (list, tuple)):
            msg = " ".join(str(item) for item in msg)
        exc_type = result.get("exc_type", "")
        if msg and exc_type:
            return f"{exc_type}: {msg}"
        return str(msg) if msg else str(result)
    return str(result)


def _safe_task_result(result: AsyncResult) -> tuple[Any | None, str | None]:
    if not result.ready():
        return (None, None)
    try:
        raw = result.get(propagate=False)
        if result.successful():
            return (raw, None)
        return (None, _format_task_error(raw))
    except Exception as exc:
        return (None, str(exc) or "Could not retrieve task result.")

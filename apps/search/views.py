"""DRF views for search API. Parse request -> service -> serialize."""

import logging
from urllib.parse import urlencode

from celery.result import AsyncResult
from rest_framework import status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.common.permissions import IsSuperuser
from apps.search.meilisearch.client import get_meilisearch_client
from apps.search.meilisearch.config import SORTABLE_ATTRIBUTES
from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.parsers import parse_facet_attributes, parse_search_query
from apps.search.serializers import FacetResultSerializer, SearchResultSerializer
from apps.search.services import SearchService, get_queryset_for_index
from apps.search.tasks import (
    clean_and_reindex_search_index,
    clear_and_reindex_all_search_indexes,
    clear_search_index,
    reindex_search_index,
)
from apps.search.types import IndexType

logger = logging.getLogger(__name__)
VALID_PER_INDEX_ACTIONS = {"reindex", "clear", "clean_and_reindex"}


class SearchViewSet(ViewSet):
    """
    Search API: list, retrieve, facets.
    index_type comes from URL (e.g. item-parts, item-images, scribes, hands, graphs).
    """

    def _get_index_type(self) -> IndexType | None:
        index_type_slug = self.kwargs.get("index_type")
        return IndexType.from_url_segment(index_type_slug) if index_type_slug else None

    def list(self, request: Request, index_type: str | None = None) -> Response:
        index = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        search_query = parse_search_query(request.query_params, index)
        service = SearchService()
        result = service.search(index, search_query)

        serializer = SearchResultSerializer(
            {
                "results": result.hits,
                "total": result.total,
                "limit": result.limit,
                "offset": result.offset,
            }
        )
        return Response(serializer.data)

    def retrieve(self, request: Request, pk: str | None = None, index_type: str | None = None) -> Response:
        index = self._get_index_type()
        if index is None or pk is None:
            return Response({"detail": "Invalid index type or id."}, status=status.HTTP_404_NOT_FOUND)

        service = SearchService()
        doc = service.get_document(index, pk)
        if doc is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(doc)

    def _build_ordering(self, request: Request, index_type: IndexType, current_sort: str | None) -> dict | None:
        allowed = list(SORTABLE_ATTRIBUTES.get(index_type, []))
        if not allowed:
            return None
        base_path = request.build_absolute_uri(request.path)
        options = []
        for attr in allowed:
            for asc, suffix in [(True, ""), (False, "-")]:
                order_val = f"{suffix}{attr}"
                params = dict(request.query_params)
                params["ordering"] = order_val
                params["offset"] = "0"
                url = f"{base_path}?{urlencode(params, doseq=True)}"
                text = f"{attr} ({'asc' if asc else 'desc'})"
                options.append({"name": order_val, "text": text, "url": url})
        return {
            "current": current_sort or (f"-{allowed[0]}" if allowed else ""),
            "options": options,
        }

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request: Request, index_type: str | None = None) -> Response:
        index = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        search_query = parse_search_query(request.query_params, index)
        facet_attributes = parse_facet_attributes(request.query_params, index)

        service = SearchService()
        search_result = service.search(index, search_query)
        facet_result = service.get_facets(index, search_query, facet_attributes)

        total = search_result.total
        limit = search_result.limit
        offset = search_result.offset
        base_url = request.build_absolute_uri(request.path)
        params = dict(request.query_params)

        next_url = None
        if offset + limit < total:
            params["offset"] = str(offset + limit)
            next_url = f"{base_url}?{urlencode(params, doseq=True)}"
        prev_url = None
        if offset > 0:
            new_offset = max(0, offset - limit)
            params["offset"] = str(new_offset)
            prev_url = f"{base_url}?{urlencode(params, doseq=True)}"

        current_ordering = (
            f"{'' if search_query.sort_spec.ascending else '-'}{search_query.sort_spec.attribute}"
            if search_query.sort_spec and search_query.sort_spec.attribute
            else None
        )
        ordering = self._build_ordering(request, index, current_ordering)

        facet_serializer = FacetResultSerializer(facet_result)
        payload = {
            **facet_serializer.data,
            "results": search_result.hits,
            "total": total,
            "limit": limit,
            "offset": offset,
            "next": next_url,
            "previous": prev_url,
            "ordering": ordering,
        }
        return Response(payload)


def _check_meilisearch_health() -> bool:
    try:
        from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

        client = get_meilisearch_client()
        client.health()
        return True
    except MeilisearchApiError, MeilisearchCommunicationError, OSError, ConnectionError:
        return False
    except Exception as exc:
        logger.warning("Meilisearch health check failed: %s", exc)
        return False


def _get_index_stats_list() -> list[dict]:
    result = []
    writer = MeilisearchIndexWriter()
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


@api_view(["GET"])
@permission_classes([IsSuperuser])
def search_stats(request):
    healthy = _check_meilisearch_health()
    if not healthy:
        return Response({"healthy": False, "total_meilisearch": 0, "total_database": 0, "indexes": []})

    try:
        indexes = _get_index_stats_list()
    except Exception as exc:
        logger.exception("Failed to gather search index stats")
        return Response(
            {"healthy": False, "total_meilisearch": 0, "total_database": 0, "indexes": [], "error": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return Response(
        {
            "healthy": True,
            "total_meilisearch": sum(idx["meilisearch_count"] for idx in indexes),
            "total_database": sum(idx["db_count"] for idx in indexes),
            "indexes": indexes,
        }
    )


@api_view(["POST"])
@permission_classes([IsSuperuser])
def search_action(request):
    action = request.data.get("action")
    index_type_segment = request.data.get("index_type")

    if not action:
        return Response({"detail": "Missing 'action' field."}, status=status.HTTP_400_BAD_REQUEST)

    if action in VALID_PER_INDEX_ACTIONS:
        if not index_type_segment:
            return Response(
                {"detail": f"'index_type' is required for action '{action}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if IndexType.from_url_segment(index_type_segment) is None:
            return Response(
                {"detail": f"Unknown index type: '{index_type_segment}'."}, status=status.HTTP_400_BAD_REQUEST
            )

        task_map = {
            "reindex": reindex_search_index,
            "clear": clear_search_index,
            "clean_and_reindex": clean_and_reindex_search_index,
        }
        task = task_map[action].delay(index_type_segment)
        return Response({"task_id": task.id, "message": f"Task '{action}' started for {index_type_segment}."})

    if action == "reindex_all":
        task_ids = [reindex_search_index.delay(idx.to_url_segment()).id for idx in IndexType]
        return Response({"task_ids": task_ids, "message": "Reindex started for all indexes."})

    if action == "clear_and_rebuild_all":
        task = clear_and_reindex_all_search_indexes.delay()
        return Response({"task_id": task.id, "message": "Clear & rebuild all started."})

    return Response({"detail": f"Unknown action '{action}'."}, status=status.HTTP_400_BAD_REQUEST)


def _format_task_error(result):
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


def _safe_task_result(result: AsyncResult):
    if not result.ready():
        return (None, None)
    try:
        raw = result.get(propagate=False)
        if result.successful():
            return (raw, None)
        return (None, _format_task_error(raw))
    except Exception as exc:
        return (None, str(exc) or "Could not retrieve task result.")


@api_view(["GET"])
@permission_classes([IsSuperuser])
def search_task_status(request, task_id):
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

    return Response(info)

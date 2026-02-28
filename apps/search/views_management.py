"""Management API views for search operations."""

import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.common.permissions import IsSuperuser
from apps.search.admin_service import SearchAdminService

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsSuperuser])
def search_stats(request):
    service = SearchAdminService()
    healthy = service.check_meilisearch_health()
    if not healthy:
        return Response({"healthy": False, "total_meilisearch": 0, "total_database": 0, "indexes": []})
    try:
        indexes = service.get_index_stats_list()
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
    service = SearchAdminService()
    try:
        payload = service.start_action(action, index_type_segment)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsSuperuser])
def search_task_status(request, task_id):
    service = SearchAdminService()
    return Response(service.task_status(task_id))

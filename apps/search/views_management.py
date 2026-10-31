import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.permissions import IsSuperuser
from apps.common.serializers import validated_data
from apps.common.services.sanity_checks import check_meilisearch
from apps.common.task_status import task_status
from apps.search.admin_service import SearchAdminService
from apps.search.quality import quality_cards
from apps.search.serializers import SearchActionSerializer

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsSuperuser])
def search_stats(request: Request) -> Response:
    unhealthy = {"healthy": False, "total_meilisearch": 0, "total_database": 0, "indexes": []}
    if not check_meilisearch()["ok"]:
        return Response(unhealthy)
    try:
        indexes = SearchAdminService().get_index_stats_list()
    except Exception:
        # Log server-side; never echo the raw exception to the caller.
        logger.exception("Failed to gather search index stats")
        return Response(
            {**unhealthy, "error": "Failed to gather search index stats."}, status=status.HTTP_503_SERVICE_UNAVAILABLE
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
def search_action(request: Request) -> Response:
    return Response(SearchAdminService().start_action(**validated_data(SearchActionSerializer, request.data)))


@api_view(["GET"])
@permission_classes([IsSuperuser])
def search_task_status(request: Request, task_id: str) -> Response:
    return Response(task_status(task_id))


@api_view(["GET"])
@permission_classes([IsSuperuser])
def quality_dashboard(request: Request) -> Response:
    return Response({"generated_at": timezone.now().isoformat(), "cards": quality_cards()})

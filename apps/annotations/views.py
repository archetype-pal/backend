from django.db.models import Count, QuerySet
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.annotations.models import Graph, GraphComponent
from apps.common.views import ActionSerializerMixin, AuditActorMixin, FilterablePrivilegedViewSet

from .serializers import (
    GraphComponentManagementSerializer,
    GraphManagementSerializer,
    GraphSerializer,
    GraphViewerWriteSerializer,
    GraphWriteManagementSerializer,
)


class GraphViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Graph.objects.select_related("allograph", "hand", "item_image")
        .prefetch_related(
            "positions",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        )
        .annotate(num_features=Count("graphcomponent__features"))
    )
    serializer_class = GraphSerializer
    pagination_class = None
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "annotation_type", "hand", "allograph"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = getattr(self.request, "user", None)

        if getattr(user, "is_authenticated", False):
            return queryset

        return queryset.exclude(annotation_type=Graph.AnnotationType.EDITORIAL)


class GraphViewerWriteViewSet(AuditActorMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = (
        Graph.objects.select_related("allograph", "hand", "item_image")
        .prefetch_related(
            "positions",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        )
        .annotate(num_features=Count("graphcomponent__features"))
    )
    serializer_class = GraphViewerWriteSerializer
    http_method_names = ["post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = getattr(self.request, "user", None)
        if getattr(user, "is_superuser", False):
            return queryset
        # Editorial annotations are managed only through the privileged
        # management API. Excluding them here means a non-superuser cannot
        # update or delete an editorial Graph by guessing its id.
        return queryset.exclude(annotation_type=Graph.AnnotationType.EDITORIAL)

    def perform_create(self, serializer):
        user = getattr(self.request, "user", None)
        if not getattr(user, "is_superuser", False):
            if serializer.validated_data.get("annotation_type") == Graph.AnnotationType.EDITORIAL:
                raise PermissionDenied("Only superusers can create editorial annotations.")
        super().perform_create(serializer)


class GraphManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = (
        # item_image__item_part is joined because the management serializer
        # reads item_image.item_part.historical_item_id per row.
        Graph.objects.select_related("allograph", "hand", "item_image", "item_image__item_part")
        .prefetch_related(
            "positions",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        )
        .annotate(num_features=Count("graphcomponent__features"))
    )
    filterset_fields = ["item_image", "annotation_type", "hand", "allograph"]

    serializer_class = GraphManagementSerializer
    action_serializer_classes = {
        "create": GraphWriteManagementSerializer,
        "update": GraphWriteManagementSerializer,
        "partial_update": GraphWriteManagementSerializer,
    }


class GraphComponentManagementViewSet(FilterablePrivilegedViewSet):
    queryset: QuerySet[GraphComponent] = (
        GraphComponent.objects.select_related("component").prefetch_related("features").all()
    )
    serializer_class = GraphComponentManagementSerializer
    filterset_fields = ["graph"]

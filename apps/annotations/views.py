from django.db.models import Count, QuerySet
from django_filters import rest_framework as filters
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.annotations.models import Graph, GraphComponent
from apps.annotations.services import GraphWriteService
from apps.common.views import ActionSerializerMixin, FilterablePrivilegedViewSet

from .serializers import (
    GraphComponentManagementSerializer,
    GraphManagementSerializer,
    GraphSerializer,
    GraphViewerWriteSerializer,
    GraphWriteManagementSerializer,
)


class _GraphWriteServiceInjectionMixin:
    """Hand the write service to the serializer at perform_* time.

    Keeps the serializer free of service construction (the plan's P3.7) while
    letting tests swap services in by overriding `get_graph_write_service`.
    """

    def get_graph_write_service(self) -> GraphWriteService:
        return GraphWriteService()

    def perform_create(self, serializer):
        serializer.save(service=self.get_graph_write_service())

    def perform_update(self, serializer):
        serializer.save(service=self.get_graph_write_service())


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


class GraphViewerWriteViewSet(_GraphWriteServiceInjectionMixin, viewsets.ModelViewSet):
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


class GraphManagementViewSet(_GraphWriteServiceInjectionMixin, ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = (
        Graph.objects.select_related("allograph", "hand", "item_image")
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

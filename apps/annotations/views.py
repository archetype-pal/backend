from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.views import FilterablePrivilegedViewSet

from .models import Graph, GraphComponent
from .serializers import (
    GraphComponentManagementSerializer,
    GraphManagementSerializer,
    GraphSerializer,
    GraphWriteManagementSerializer,
)


class GraphViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Graph.objects.select_related("allograph", "hand", "item_image").prefetch_related(
        "positions",
        "graphcomponent_set__component",
        "graphcomponent_set__features",
    )
    serializer_class = GraphSerializer
    pagination_class = None
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "annotation_type", "hand"]


class GraphManagementViewSet(FilterablePrivilegedViewSet):
    queryset = (
        Graph.objects.select_related("allograph", "hand", "item_image")
        .prefetch_related(
            "positions",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        )
        .all()
    )
    filterset_fields = ["item_image", "annotation_type", "hand", "allograph"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return GraphWriteManagementSerializer
        return GraphManagementSerializer


class GraphComponentManagementViewSet(FilterablePrivilegedViewSet):
    queryset = GraphComponent.objects.select_related("component").prefetch_related("features").all()
    serializer_class = GraphComponentManagementSerializer
    filterset_fields = ["graph"]

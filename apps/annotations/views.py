from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.views import ActionSerializerMixin, FilterablePrivilegedViewSet

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


class GraphManagementViewSet(ActionSerializerMixin, FilterablePrivilegedViewSet):
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

    serializer_class = GraphManagementSerializer
    action_serializer_classes = {
        "create": GraphWriteManagementSerializer,
        "update": GraphWriteManagementSerializer,
        "partial_update": GraphWriteManagementSerializer,
    }


class GraphComponentManagementViewSet(FilterablePrivilegedViewSet):
    queryset = GraphComponent.objects.select_related("component").prefetch_related("features").all()
    serializer_class = GraphComponentManagementSerializer
    filterset_fields = ["graph"]

from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.api.permissions import IsAdminUser
from apps.annotations.models import Graph, GraphComponent

from .admin_serializers import (
    GraphAdminSerializer,
    GraphComponentAdminSerializer,
    GraphWriteAdminSerializer,
)


class GraphAdminViewSet(viewsets.ModelViewSet):
    queryset = Graph.objects.select_related(
        "allograph", "hand", "item_image"
    ).prefetch_related(
        "positions",
        "graphcomponent_set__component",
        "graphcomponent_set__features",
    ).all()
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "annotation_type", "hand", "allograph"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return GraphWriteAdminSerializer
        return GraphAdminSerializer


class GraphComponentAdminViewSet(viewsets.ModelViewSet):
    queryset = GraphComponent.objects.select_related("component").prefetch_related("features").all()
    serializer_class = GraphComponentAdminSerializer
    permission_classes = [IsAdminUser]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["graph"]

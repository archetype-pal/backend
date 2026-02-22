from apps.annotations.models import Graph, GraphComponent
from apps.common.api.base_admin_views import FilterableAdminViewSet

from .admin_serializers import (
    GraphAdminSerializer,
    GraphComponentAdminSerializer,
    GraphWriteAdminSerializer,
)


class GraphAdminViewSet(FilterableAdminViewSet):
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
            return GraphWriteAdminSerializer
        return GraphAdminSerializer


class GraphComponentAdminViewSet(FilterableAdminViewSet):
    queryset = GraphComponent.objects.select_related("component").prefetch_related("features").all()
    serializer_class = GraphComponentAdminSerializer
    filterset_fields = ["graph"]

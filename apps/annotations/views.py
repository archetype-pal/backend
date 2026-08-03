from django.db.models import Count, QuerySet
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.annotations.models import Graph, GraphComponent
from apps.common.audit import audit_actor
from apps.common.views import (
    ActionSerializerMixin,
    AuditActorMixin,
    FilterablePrivilegedViewSet,
    TrashableViewSetMixin,
)

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
        # Django drops Meta.ordering once a GROUP BY is present, so the annotate above
        # silently leaves this public endpoint unordered. Order explicitly.
        .order_by("id")
    )
    serializer_class = GraphSerializer
    pagination_class = None
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "annotation_type", "hand", "allograph"]

    def get_queryset(self):
        queryset = super().get_queryset().filter(deleted_at__isnull=True)
        user = getattr(self.request, "user", None)

        if getattr(user, "is_authenticated", False):
            return queryset

        return queryset.exclude(annotation_type=Graph.AnnotationType.EDITORIAL)


class GraphViewerWriteViewSet(TrashableViewSetMixin, AuditActorMixin, viewsets.ModelViewSet):
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
        # Trashed rows are invisible here: they can't be patched or re-deleted;
        # restore/purge live on the management API only.
        queryset = super().get_queryset().filter(deleted_at__isnull=True)
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

    def perform_update(self, serializer):
        # Mirrors perform_create: without this, a non-superuser could PATCH an
        # annotation *to* editorial and lock themselves out (the queryset above
        # hides editorial rows from them, so they could never revert it). The
        # reverse direction needs no guard — editorial rows 404 for them here.
        user = getattr(self.request, "user", None)
        if not getattr(user, "is_superuser", False):
            if serializer.validated_data.get("annotation_type") == Graph.AnnotationType.EDITORIAL:
                raise PermissionDenied("Only superusers can make an annotation editorial.")
        super().perform_update(serializer)


class GraphManagementViewSet(TrashableViewSetMixin, ActionSerializerMixin, FilterablePrivilegedViewSet):
    queryset = (
        # item_image__item_part is joined because the management serializer
        # reads item_image.item_part.historical_item_id per row; deleted_by
        # because the trash list shows who trashed each row.
        Graph.objects.select_related("allograph", "hand", "item_image", "item_image__item_part", "deleted_by")
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

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in ("restore", "purge"):
            # Restore/purge target rows in the trash; a live id 404s.
            return queryset.filter(deleted_at__isnull=False)
        if self.action == "list" and self.request.query_params.get("deleted") in ("true", "1"):
            return queryset.filter(deleted_at__isnull=False).order_by("-deleted_at")
        return queryset.filter(deleted_at__isnull=True)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        graph = self.get_object()
        with audit_actor(request.user):
            graph.restore()
        return Response(self.get_serializer(graph).data)

    @action(detail=True, methods=["delete"])
    def purge(self, request, pk=None):
        """Hard-delete a trashed row. Unlike trash, this is a real delete: the
        pre_delete corresp-strip and the EditEvent `deleted` signal both fire."""
        graph = self.get_object()
        with audit_actor(request.user):
            graph.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GraphComponentManagementViewSet(FilterablePrivilegedViewSet):
    queryset: QuerySet[GraphComponent] = (
        GraphComponent.objects.select_related("component")
        .prefetch_related("features")
        # Components of a trashed graph are hidden with it.
        .filter(graph__deleted_at__isnull=True)
    )
    serializer_class = GraphComponentManagementSerializer
    filterset_fields = ["graph"]

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
    )
    serializer_class = GraphSerializer
    pagination_class = None
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["item_image", "annotation_type", "hand", "allograph"]

    def get_queryset(self):
        queryset = super().get_queryset().live()
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
        # Restore/purge live on the management API, so trashed rows are out of reach here.
        queryset = super().get_queryset().live()
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
    # Dict form so the trash can filter a `deleted_at` range. `exact` takes no
    # suffix, so the existing `?annotation_type=` / `?hand=` params are unchanged.
    filterset_fields = {
        "item_image": ["exact"],
        "annotation_type": ["exact"],
        "hand": ["exact"],
        "allograph": ["exact"],
        # Username, matching what the serializer exposes.
        "deleted_by__username": ["exact"],
        "deleted_at": ["gte", "lte"],
    }

    serializer_class = GraphManagementSerializer
    action_serializer_classes = {
        "create": GraphWriteManagementSerializer,
        "update": GraphWriteManagementSerializer,
        "partial_update": GraphWriteManagementSerializer,
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in ("restore", "purge"):
            # Both target the trash, so a live id 404s.
            return queryset.trashed()
        if self.action == "list" and self.request.query_params.get("deleted") in ("true", "1"):
            return queryset.trashed().order_by("-deleted_at")
        return queryset.live()

    @action(detail=False, methods=["get"], url_path="trash-actors")
    def trash_actors(self, request):
        """Usernames that currently have something in the trash.

        Backs the "deleted by" filter, so it never offers a value that returns
        no rows. Not `get_queryset()`: its `annotate()` GROUP BY would break the
        DISTINCT. The explicit `order_by` overrides `Meta.ordering`, which would
        otherwise add `id` to the SELECT and make rows distinct per row.
        """
        usernames = (
            Graph.objects.trashed()
            .exclude(deleted_by__isnull=True)
            .order_by("deleted_by__username")
            .values_list("deleted_by__username", flat=True)
            .distinct()
        )
        return Response(list(usernames))

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
        .filter(graph__deleted_at__isnull=True)
    )
    serializer_class = GraphComponentManagementSerializer
    filterset_fields = ["graph"]

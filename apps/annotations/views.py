from django.db.models import Count, QuerySet
from django_filters import rest_framework as filters
from rest_framework import serializers, status, viewsets
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


def _management_optimized(queryset):
    """Joins and annotation that `GraphManagementSerializer` needs, on any manager.

    Shared so the live list and the trash branches cannot drift apart:
    item_image__item_part because the serializer reads
    item_image.item_part.historical_item_id per row, deleted_by because the
    trash list shows who trashed each row.
    """
    return (
        queryset.select_related("allograph", "hand", "item_image", "item_image__item_part", "deleted_by")
        .prefetch_related(
            "positions",
            "graphcomponent_set__component",
            "graphcomponent_set__features",
        )
        .annotate(num_features=Count("graphcomponent__features"))
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
        queryset = super().get_queryset()
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
    # Graph.objects hides trashed rows, so every action here is safe by
    # default; only the trash branches below opt into all_objects.
    queryset = _management_optimized(Graph.objects.all())
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
        if self.action in ("restore", "purge"):
            # Both target the trash, so a live id 404s.
            return _management_optimized(Graph.all_objects.trashed())
        if self.action == "retrieve":
            # A row the trash list just handed out must be addressable by detail.
            return _management_optimized(Graph.all_objects.all())
        if self.action == "list":
            # BooleanField, not `in ("true", "1")`: `?deleted=True` — what requests
            # sends for a Python bool — must not silently return the live list.
            # allow_null so absent/blank/`null` mean "live", as clients emit them.
            field = serializers.BooleanField(allow_null=True)
            if field.to_internal_value(self.request.query_params.get("deleted")):
                return _management_optimized(Graph.all_objects.trashed()).order_by("-deleted_at")
        return super().get_queryset()

    @action(detail=False, methods=["get"], url_path="trash-actors")
    def trash_actors(self, request):
        """Usernames that currently have something in the trash.

        Backs the "deleted by" filter, so it never offers a value that returns
        no rows. Not `get_queryset()`: its `annotate()` GROUP BY would break the
        DISTINCT. The explicit `order_by` overrides `Meta.ordering`, which would
        otherwise add `id` to the SELECT and make rows distinct per row.
        """
        usernames = (
            Graph.all_objects.trashed()
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

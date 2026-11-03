"""Viewset bases and mixins every management API is built from."""

from django_filters import rest_framework as filters
from rest_framework import serializers, viewsets
from rest_framework.filters import SearchFilter

from apps.common.filters import StableOrderingFilter
from apps.common.permissions import IsSuperuser


class TrashableViewSetMixin:
    """Turn DRF's destroy into a soft delete for SoftDeleteModel rows.

    List before ModelViewSet so this perform_destroy wins. Being a save(), it
    does not fire pre_delete/post_delete — only a purge does.
    """

    def perform_destroy(self, instance):
        instance.soft_delete(user=getattr(self.request, "user", None))


class BasePrivilegedViewSet(viewsets.ModelViewSet):
    """All privileged ViewSets require superuser permissions."""

    permission_classes = [IsSuperuser]


class ActionSerializerMixin:
    """Map DRF actions to serializers to avoid repetitive conditionals."""

    action_serializer_classes: dict[str, type[serializers.Serializer]] = {}

    def get_serializer_class(self) -> type[serializers.Serializer]:
        serializer_class = self.action_serializer_classes.get(getattr(self, "action", ""))
        if serializer_class is not None:
            return serializer_class
        return super().get_serializer_class()  # type: ignore[misc, no-any-return]


class FilterablePrivilegedViewSet(BasePrivilegedViewSet):
    """Privileged ViewSet with DjangoFilterBackend and SearchFilter pre-configured."""

    filter_backends = [filters.DjangoFilterBackend, SearchFilter]


class SortablePrivilegedViewSet(FilterablePrivilegedViewSet):
    """Filterable ViewSet with `?ordering=` over each subclass's own `ordering_fields`; pages keep a fixed order."""

    filter_backends = [filters.DjangoFilterBackend, SearchFilter, StableOrderingFilter]
    ordering_fields: list[str] = []


class UnpaginatedPrivilegedViewSet(BasePrivilegedViewSet):
    """Privileged ViewSet for small lookup tables (no pagination)."""

    pagination_class = None

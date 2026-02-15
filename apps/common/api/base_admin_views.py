"""
Base ViewSet classes for admin (backoffice) API endpoints.

These reduce boilerplate by pre-configuring permission classes,
filter backends, and pagination settings that are common to all
admin ViewSets.
"""

from django_filters import rest_framework as filters
from rest_framework import viewsets

from apps.common.api.permissions import IsAdminUser


class BaseAdminViewSet(viewsets.ModelViewSet):
    """All admin ViewSets require staff permissions."""

    permission_classes = [IsAdminUser]


class FilterableAdminViewSet(BaseAdminViewSet):
    """Admin ViewSet with DjangoFilterBackend pre-configured."""

    filter_backends = [filters.DjangoFilterBackend]


class UnpaginatedAdminViewSet(BaseAdminViewSet):
    """Admin ViewSet for small lookup tables (no pagination)."""

    pagination_class = None

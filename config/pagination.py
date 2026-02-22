"""Custom DRF pagination with a bounded limit to reduce DoS risk."""

from rest_framework.pagination import LimitOffsetPagination


class BoundedLimitOffsetPagination(LimitOffsetPagination):
    """LimitOffsetPagination with a maximum limit (100) for all list endpoints."""

    default_limit = 20
    max_limit = 100

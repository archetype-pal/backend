from typing import Any, cast

from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request


def with_pk_tiebreak(queryset: QuerySet) -> QuerySet:
    """*queryset* in its own order (`Meta.ordering` if `annotate()` dropped it), then by pk, so pages never overlap.

    A `values()` query is left alone: ordering by pk would add pk to its GROUP BY.
    """
    query = queryset.query
    if query.values_select or query.combinator:
        return queryset
    return queryset.order_by(*(query.order_by or queryset.model._meta.ordering), "pk")


class BoundedLimitOffsetPagination(LimitOffsetPagination):
    """LimitOffsetPagination with a maximum limit (100) for all list endpoints; pages never overlap."""

    default_limit = 20
    max_limit = 100

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> list | None:
        if isinstance(queryset, QuerySet):
            queryset = with_pk_tiebreak(queryset)
        return cast(list | None, super().paginate_queryset(queryset, request, view))

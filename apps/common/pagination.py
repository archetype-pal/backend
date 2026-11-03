from typing import Any

from django.db.models import F, QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request


def _names_pk(term: Any, pk_names: set[str]) -> bool:
    if isinstance(term, str):
        return term.lstrip("-") in pk_names
    expression = getattr(term, "expression", None)
    return isinstance(expression, F) and expression.name in pk_names


def with_pk_tiebreak(queryset: QuerySet) -> QuerySet:
    """*queryset* in its own order, then by pk, so no two rows tie and pages never overlap.

    The own order is the `order_by`, else `Meta.ordering`, restored here because
    `annotate()` with an aggregate drops it (no `Meta.ordering` crosses a
    relation, so this adds no join). A `values()` query is left alone: ordering
    by pk would add pk to its GROUP BY.
    """
    query = queryset.query
    if query.values_select or query.combinator:
        return queryset
    terms = list(query.order_by or (queryset.model._meta.ordering if query.default_ordering else ()))
    if any(_names_pk(term, {"pk", queryset.model._meta.pk.name}) for term in terms):
        return queryset
    return queryset.order_by(*terms, "pk")


class BoundedLimitOffsetPagination(LimitOffsetPagination):
    """LimitOffsetPagination with a maximum limit (100) for all list endpoints; pages never overlap."""

    default_limit = 20
    max_limit = 100

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> list | None:
        if isinstance(queryset, QuerySet):
            queryset = with_pk_tiebreak(queryset)
        page: list | None = super().paginate_queryset(queryset, request, view)
        return page

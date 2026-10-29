"""DRF filter backends shared by the management viewsets."""

from typing import Any

from django.db.models import F, OrderBy, QuerySet
from rest_framework.filters import OrderingFilter
from rest_framework.request import Request


class StableOrderingFilter(OrderingFilter):
    """Orders every paged list, so pages never overlap; pk breaks ties.

    `?ordering=` sorts by the view's `ordering_fields`, nulls last; unknown fields are ignored.
    Without it: the view's `ordering`, the queryset's order_by, then Meta.ordering, which annotate() drops.
    """

    def filter_queryset(self, request: Request, queryset: QuerySet, view: Any) -> QuerySet:
        params = request.query_params.get(self.ordering_param)
        chosen = (
            self.remove_invalid_fields(queryset, [p.strip() for p in params.split(",")], view, request)
            if params
            else []
        )
        terms: list[OrderBy | str]
        if chosen:
            terms = [F(f[1:]).desc(nulls_last=True) if f.startswith("-") else F(f).asc(nulls_last=True) for f in chosen]
        else:
            terms = list(self.get_default_ordering(view) or queryset.query.order_by or queryset.model._meta.ordering)
        if not any(str(term).lstrip("-") in ("pk", "id") for term in (chosen or terms)):
            terms.append("pk")
        return queryset.order_by(*terms)

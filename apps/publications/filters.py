"""Search backends for the publications management endpoints."""

from functools import reduce
import operator

from django.db.models import Q
from django.utils.html import escape
from rest_framework.filters import SearchFilter


class EscapedTextSearchFilter(SearchFilter):
    """SearchFilter that also matches each term HTML-escaped. Guest comments are stored
    escaped (create_public_comment), so a raw search for O'Brien or & would miss them."""

    def filter_queryset(self, request, queryset, view):
        search_fields = self.get_search_fields(view, request)
        terms = self.get_search_terms(request)
        if not search_fields or not terms:
            return queryset
        lookups = [self.construct_search(str(field), queryset) for field in search_fields]
        for term in terms:
            variants = {term, escape(term)}
            queryset = queryset.filter(
                reduce(operator.or_, (Q(**{lookup: value}) for lookup in lookups for value in variants))
            )
        return queryset

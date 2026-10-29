"""django-filter FilterSets for the graph endpoints."""

from django_filters import rest_framework as filters

from .models import Graph


class NumberInFilter(filters.BaseInFilter, filters.NumberFilter):
    pass


class GraphFilterSet(filters.FilterSet):
    # An empty id__in= is standard django-filter BaseInFilter behaviour: an
    # empty parsed value is treated as "filter not applied", same as omitting
    # the param entirely — not special-cased here since that already matches
    # this endpoint's normal (unpaginated, unfiltered) behaviour with no
    # id__in at all. fetchGraphsByIds (frontend) never sends an empty list.
    id__in = NumberInFilter(field_name="id", lookup_expr="in")

    class Meta:
        model = Graph
        # id__in is declared above; django-filter registers declared filters
        # automatically, so listing it here too would be redundant.
        fields = ["item_image", "annotation_type", "hand", "allograph"]

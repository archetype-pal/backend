import operator

from django.core.exceptions import ImproperlyConfigured
from rest_framework.filters import BaseFilterBackend, OrderingFilter

from haystack_rest.query import FacetQueryBuilder, FilterQueryBuilder


class BaseHaystackFilterBackend(BaseFilterBackend):
    """
    A base class from which all Haystack filter backend classes should inherit.
    """

    query_builder_class = None

    @staticmethod
    def get_request_filters(request):
        return request.query_params.copy()

    def apply_filters(self, queryset, applicable_filters=None, applicable_exclusions=None):
        """
        Apply constructed filters and excludes and return the queryset

        :param queryset: queryset to filter
        :param applicable_filters: filters which are passed directly to queryset.filter()
        :param applicable_exclusions: filters which are passed directly to queryset.exclude()
        :returns filtered queryset
        """
        if applicable_filters:
            queryset = queryset.filter(applicable_filters)
        if applicable_exclusions:
            queryset = queryset.exclude(applicable_exclusions)
        return queryset

    def build_filters(self, view, filters=None):
        """
        Get the query builder instance and return constructed query filters.
        """
        query_builder = self.get_query_builder(backend=self, view=view)
        return query_builder.build_query(**(filters if filters else {}))

    def process_filters(self, filters, queryset, view):
        """
        Convenient hook to do any post-processing of the filters before they
        are applied to the queryset.
        """
        return filters

    def filter_queryset(self, request, queryset, view):
        """
        Return the filtered queryset.
        """
        applicable_filters, applicable_exclusions = self.build_filters(view, filters=self.get_request_filters(request))
        return self.apply_filters(
            queryset=queryset,
            applicable_filters=self.process_filters(applicable_filters, queryset, view),
            applicable_exclusions=self.process_filters(applicable_exclusions, queryset, view),
        )

    def get_query_builder(self, *args, **kwargs):
        """
        Return the query builder class instance that should be used to
        build the query which is passed to the search engine backend.
        """
        query_builder = self.get_query_builder_class()
        return query_builder(*args, **kwargs)

    def get_query_builder_class(self):
        """
        Return the class to use for building the query.
        Defaults to using `self.query_builder_class`.

        You may want to override this if you need to provide different
        methods of building the query sent to the search engine backend.
        """
        assert self.query_builder_class is not None, (
            f"'{self.__class__.__name__}' should either include a `query_builder_class` attribute, "
            "or override the `get_query_builder_class()` method."
        )
        return self.query_builder_class


class HaystackFilter(BaseHaystackFilterBackend):
    """
    A filter backend that compiles a haystack compatible filtering query.
    """

    query_builder_class = FilterQueryBuilder
    default_operator = operator.and_
    default_same_param_operator = operator.or_


class HaystackFacetFilter(BaseHaystackFilterBackend):
    """
    Filter backend for faceting search results.
    This backend does not apply regular filtering.

    Faceting field options can be set via the serializer ``field_options``
    and overridden by query parameters (e.g. ?field=limit:10).
    """

    query_builder_class = FacetQueryBuilder

    def apply_filters(self, queryset, applicable_filters=None, applicable_exclusions=None):
        for field, options in applicable_filters["field_facets"].items():
            queryset = queryset.facet(field, **options)
        return queryset

    def filter_queryset(self, request, queryset, view):
        return self.apply_filters(queryset, self.build_filters(view, filters=self.get_request_filters(request)))


class HaystackOrderingFilter(OrderingFilter):
    """Ordering filter for Haystack views (ordering_fields from index_models)."""

    def get_default_valid_fields(self, queryset, view, context=None):
        context = context or {}
        return super().get_default_valid_fields(queryset, view, context)

    def get_valid_fields(self, queryset, view, context=None):
        context = context or {}
        valid_fields = getattr(view, "ordering_fields", self.ordering_fields)
        if valid_fields is None:
            return self.get_default_valid_fields(queryset, view, context)
        if valid_fields == "__all__":
            if not queryset.query.models:
                raise ImproperlyConfigured(
                    f"Cannot use {self.__class__.__name__} with '__all__' as 'ordering_fields' on a view "
                    "with no 'index_models'. Set 'ordering_fields' or 'index_models'."
                )
            valid_fields = list(
                {(f.name, f.verbose_name) for model in queryset.query.models for f in model._meta.fields}
            )
        else:
            valid_fields = [(item, item) if isinstance(item, str) else item for item in valid_fields]
        return valid_fields

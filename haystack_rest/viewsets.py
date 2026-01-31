from django.http import Http404
from haystack.backends import SQ
from haystack.query import SearchQuerySet
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import ViewSetMixin

from haystack_rest.filters import HaystackFilter


class HaystackGenericAPIView(GenericAPIView):
    """
    Base class for all haystack generic views.
    """

    # Use `index_models` to filter on which search index models we
    # should include in the search result.
    index_models = []

    object_class = SearchQuerySet
    query_object = SQ

    # Override document_uid_field with whatever field in your index
    # you use to uniquely identify a single document. This value will be
    # used wherever the view references the `lookup_field` kwarg.
    document_uid_field = "id"
    lookup_sep = ","

    # If set to False, DB lookups are done on a per-object basis,
    # resulting in in many individual trips to the database. If True,
    # the SearchQuerySet will group similar objects into a single query.
    load_all = False

    filter_backends = [HaystackFilter]

    def get_queryset(self, index_models=None):
        """Return search queryset, optionally scoped to index_models."""
        index_models = index_models or []
        if self.queryset is not None and isinstance(self.queryset, self.object_class):
            queryset = self.queryset.all()
        else:
            queryset = self.object_class()._clone()
            if index_models:
                queryset = queryset.models(*index_models)
            elif self.index_models:
                queryset = queryset.models(*self.index_models)
        return queryset

    def get_object(self):
        """Fetch a single document by lookup (e.g. pk)."""
        queryset = self.get_queryset()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        if lookup_url_kwarg not in self.kwargs:
            raise AttributeError(
                f"Expected view {self.__class__.__name__} to be called with a URL keyword argument "
                f"named '{lookup_url_kwarg}'. Fix your URL conf, or set the `.lookup_field` attribute."
            )
        queryset = queryset.filter(
            self.query_object((self.document_uid_field, self.kwargs[lookup_url_kwarg]))
        )
        count = queryset.count()
        if count == 1:
            return queryset[0]
        if count > 1:
            raise Http404("Multiple results match the query. Expected a single result.")
        raise Http404("No result matches the query.")

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)

        if self.load_all:
            queryset = queryset.load_all()

        return queryset


class HaystackViewSet(RetrieveModelMixin, ListModelMixin, ViewSetMixin, HaystackGenericAPIView):
    """
    The HaystackViewSet class provides the default ``list()`` and
    ``retrieve()`` actions with a haystack index as it's data source.
    """

    pass

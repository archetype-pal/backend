from rest_framework.decorators import action
from rest_framework.response import Response

from haystack_rest.filters import HaystackFacetFilter


class FacetMixin:
    """
    Mixin class for supporting faceting on an API View.
    """

    facet_filter_backends = [HaystackFacetFilter]
    facet_serializer_class = None
    facet_objects_serializer_class = None
    facet_query_params_text = "selected_facets"

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request):
        """List route for faceted results (e.g. GET /search/facets/)."""
        queryset = self.filter_facet_queryset(self.get_queryset())

        # Handles facets options passed in the url
        for facet in request.query_params.getlist(self.facet_query_params_text):
            if ":" not in facet:
                continue

            field, value = facet.split(":", 1)
            if value:
                queryset = queryset.narrow(f'{field}:"{queryset.query.clean(value)}"')

        serializer = self.get_facet_serializer(queryset.facet_counts(), objects=queryset, many=False)
        return Response(serializer.data)

    def filter_facet_queryset(self, queryset):
        """Apply facet filter backends to the queryset."""
        for backend in self.facet_filter_backends:
            queryset = backend().filter_queryset(self.request, queryset, self)

        if self.load_all:
            queryset = queryset.load_all()

        return queryset

    def get_facet_serializer(self, *args, **kwargs):
        """Return the facet serializer instance for faceted output."""
        assert "objects" in kwargs, "get_facet_serializer() requires objects=..."

        facet_serializer_class = self.get_facet_serializer_class()
        kwargs["context"] = self.get_serializer_context()
        kwargs["context"].update(
            {
                "objects": kwargs.pop("objects"),
                "facet_query_params_text": self.facet_query_params_text,
            }
        )
        return facet_serializer_class(*args, **kwargs)

    def get_facet_serializer_class(self):
        """Return the class used to serialize facets (facet_serializer_class)."""
        if self.facet_serializer_class is None:
            raise AttributeError(
                f"{self.__class__.__name__} should either include a `facet_serializer_class` attribute, "
                f"or override {self.__class__.__name__}.get_facet_serializer_class() method."
            )
        return self.facet_serializer_class

    def get_facet_objects_serializer(self, *args, **kwargs):
        """Return the serializer instance for faceted object list."""
        facet_objects_serializer_class = self.get_facet_objects_serializer_class()
        kwargs["context"] = self.get_serializer_context()
        return facet_objects_serializer_class(*args, **kwargs)

    def get_facet_objects_serializer_class(self):
        """Return the serializer class for faceted objects (default: view serializer_class)."""
        return self.facet_objects_serializer_class or super().get_serializer_class()

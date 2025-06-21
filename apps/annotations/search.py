from rest_framework import serializers

from haystack_rest.mixins import FacetMixin
from haystack_rest.serializers import HaystackFacetSerializer, HaystackSerializer
from haystack_rest.viewsets import HaystackViewSet

from .models import Graph
from .search_indexes import GraphIndex


class GraphSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")

    class Meta:
        index_classes = [GraphIndex]

        fields = [
            "id",
            "item_image",
            "coordinates",
            "is_annotated",
            "repository_name",
            "repository_city",
            "shelfmark",
            "date",
            "components",
            "features",
            "component_features",
            "positions",
        ]


class GraphFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta:
        fields = [
            "repository_city",
            "repository_name",
            "allograph",
            "character",
            "character_type",
            "components",
            "features",
            "component_features",
            "positions",
        ]
        field_options = {
            "repository_city": {},
            "repository_name": {},
            "allograph": {},
            "character": {},
            "character_type": {},
            "components": {},
            "features": {},
            "component_features": {},
            "positions": {},
        }


class GraphSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [Graph]
    serializer_class = GraphSearchSerializer
    facet_serializer_class = GraphFacetSearchSerializer

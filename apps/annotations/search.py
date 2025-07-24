from rest_framework import serializers

from apps.common.mixins import CustomFacetMixin as FacetMixin
from haystack_rest.filters import HaystackFilter, HaystackOrderingFilter
from haystack_rest.serializers import HaystackFacetSerializer, HaystackSerializer
from haystack_rest.viewsets import HaystackViewSet

from .models import Graph
from .search_indexes import GraphIndex


class GraphSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")
    coordinates = serializers.JSONField()

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
    filter_backends = [HaystackFilter, HaystackOrderingFilter]
    
    ordering_fields = [
        "repository_name_exact",
        "repository_city_exact",
        "shelfmark_exact",
        "allograph_exact",
    ]

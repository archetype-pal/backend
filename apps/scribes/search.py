from rest_framework import serializers

from haystack_rest.mixins import FacetMixin
from haystack_rest.serializers import HaystackFacetSerializer, HaystackSerializer
from haystack_rest.viewsets import HaystackViewSet

from .models import Hand, Scribe
from .search_indexes import HandIndex, ScribeIndex


class ScribeSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")

    class Meta:
        index_classes = [ScribeIndex]

        fields = ["id", "name", "period", "scriptorium"]


class ScribeFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta(ScribeSearchSerializer.Meta):
        field_options = {
            "scriptorium": {},
        }


class ScribeSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [Scribe]
    serializer_class = ScribeSearchSerializer
    facet_serializer_class = ScribeFacetSearchSerializer


class HandSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")

    class Meta:
        index_classes = [HandIndex]

        fields = [
            "id",
            "name",
            "place",
            "description",
            "repository_name",
            "repository_city",
            "shelfmark",
            "catalogue_numbers",
        ]


class HandFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta(HandSearchSerializer.Meta):
        field_options = {
            "repository_city": {},
            "repository_name": {},
            "catalogue_numbers": {},
        }


class HandSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [Hand]
    serializer_class = HandSearchSerializer
    facet_serializer_class = HandFacetSearchSerializer

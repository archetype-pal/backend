from rest_framework import serializers

from apps.common.mixins import CustomFacetMixin as FacetMixin
from haystack_rest.filters import HaystackFilter, HaystackOrderingFilter
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
    filter_backends = [HaystackFilter, HaystackOrderingFilter]
    
    ordering_fields = [
        "name_exact",
        "scriptorium_exact",
    ]


class HandSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")

    class Meta:
        index_classes = [HandIndex]

        fields = [
            "id",
            "name",
            "repository_name",
            "repository_city",
            "shelfmark",
            "place",
            "date",
            "catalogue_numbers",
            "description",
        ]


class HandFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta(HandSearchSerializer.Meta):
        field_options = {
            "repository_city": {},
            "repository_name": {},
            "place": {},
        }


class HandSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [Hand]
    serializer_class = HandSearchSerializer
    facet_serializer_class = HandFacetSearchSerializer
    filter_backends = [HaystackFilter, HaystackOrderingFilter]
    
    ordering_fields = [
        "name_exact",
        "repository_name_exact",
        "repository_city_exact",
        "shelfmark_exact",
        "place_exact",
        "catalogue_numbers_exact",
    ]

from drf_haystack.mixins import FacetMixin
from drf_haystack.serializers import HaystackFacetSerializer, HaystackSerializer
from drf_haystack.viewsets import HaystackViewSet

from .models import Scribe
from .search_indexes import HandIndex, ScribeIndex


class ScribeSearchSerializer(HaystackSerializer):
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
    class Meta:
        index_classes = [HandIndex]

        fields = [
            "id",
            "name",
            "date",
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

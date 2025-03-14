from drf_haystack.mixins import FacetMixin
from drf_haystack.serializers import HaystackFacetSerializer, HaystackSerializer
from drf_haystack.viewsets import HaystackViewSet

from .models import ItemImage, ItemPart
from .search_indexes import ItemImageIndex, ItemPartIndex


class ManuscriptSearchSerializer(HaystackSerializer):
    class Meta:
        index_classes = [ItemPartIndex]

        fields = [
            "id",
            "repository_city",
            "repository_name",
            "shelfmark",
            "catalogue_numbers",
            "date",
            "type",
            "number_of_images",
            "image_availability",
            "issuer_name",
            "named_beneficiary",
        ]


class ManuscriptFacetSearchSerializer(HaystackFacetSerializer):

    serialize_objects = True

    class Meta(ManuscriptSearchSerializer.Meta):
        field_options = {
            "image_availability": {},
            "type": {},
            "repository_city": {},
            "repository_name": {},
            "named_beneficiary": {},
            "issuer_name": {},
        }


class ManuscriptSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [ItemPart]
    serializer_class = ManuscriptSearchSerializer
    facet_serializer_class = ManuscriptFacetSearchSerializer


class ImageSearchSerializer(HaystackSerializer):
    class Meta:
        index_classes = [ItemImageIndex]

        fields = [
            "id",
            "text",
            "image",
            "repository_city",
            "repository_name",
            "shelfmark",
            "locus",
            "date",
            "number_of_annotations",
            "type",
            "issuer_name",
            "named_beneficiary",
        ]


class ImageFacetSearchSerializer(HaystackFacetSerializer):

    serialize_objects = True

    class Meta(ImageSearchSerializer.Meta):
        field_options = {
            "locus": {},
            "type": {},
            "repository_city": {},
            "repository_name": {},
            "issuer_name": {},
            "named_beneficiary": {},
            "component": {},  # not implemented yet!
            "feature": {},  # not implemented yet!
        }


class ImageSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [ItemImage]
    serializer_class = ImageSearchSerializer
    facet_serializer_class = ImageFacetSearchSerializer

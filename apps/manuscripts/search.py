from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.common.mixins      import CustomFacetMixin   as FacetMixin
from haystack_rest.serializers import HaystackFacetSerializer, HaystackSerializer
from haystack_rest.viewsets import HaystackViewSet
from haystack_rest.filters import HaystackFilter, HaystackOrderingFilter

from .models import ItemImage, ItemPart
from .search_indexes import ItemImageIndex, ItemPartIndex


class ManuscriptSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")

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
            "date",
        ]


class ManuscriptFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta:
        index_classes = [ItemPartIndex]
        fields = [
            "image_availability",
            "type",
            "repository_city",
            "repository_name",
            "named_beneficiary",
            "date_min",  # Add date_min for faceting
            "date_max",  # Add date_max for faceting
            "format",
        ]
        field_options = {
            "image_availability": {},
            "type": {},
            "repository_city": {},
            "repository_name": {},
            "format": {},
            "date_min": {},  # No special options needed; simple integer faceting
            "date_max": {},  # No special options needed; simple integer faceting
        }


class ManuscriptSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [ItemPart]
    serializer_class = ManuscriptSearchSerializer
    facet_serializer_class = ManuscriptFacetSearchSerializer
    filter_backends = [HaystackFilter, HaystackOrderingFilter]
    
    ordering_fields = [
        "repository_name_exact",
        "repository_city_exact",
        "shelfmark_exact",
        "catalogue_numbers_exact",
        "type_exact",
        "number_of_images_exact",
    ]

    def filter_facet_queryset(self, queryset):
        params = self.request.query_params
        date_min = params.get("min_date")
        date_max = params.get("max_date")
        at_most_or_least = params.get("at_most_or_least")
        date_diff = params.get("date_diff")

        try:
            if date_min:
                date_min = int(date_min)
            if date_max:
                date_max = int(date_max)
            if date_diff:
                date_diff = int(date_diff)

        except ValueError as err:
            raise ValidationError({"detail": "Invalid value for filtering parameters."}) from err

        # Construct range filters
        range_filter = Q()
        if date_min is not None:
            range_filter &= Q(date_min__gte=date_min)

        if date_max is not None:
            range_filter &= Q(date_max__lte=date_max)

        # Handle precision filters
        precision_filter = Q()
        if at_most_or_least and date_diff and date_min is not None:
            if at_most_or_least == "at most":
                # Adjust date_max to be within (date_min + date_diff)
                precision_filter &= Q(date_max__lte=(date_min + date_diff))
            elif at_most_or_least == "at least":
                # Adjust date_max to be >= (date_min + date_diff)
                precision_filter &= Q(date_max__gte=(date_min + date_diff))

        # Combine filters
        combined_filter = range_filter & precision_filter

        # Apply filters to queryset
        queryset = queryset.filter(combined_filter)

        return super().filter_facet_queryset(queryset)


class ImageSearchSerializer(HaystackSerializer):
    id = serializers.IntegerField(source="model_id")

    class Meta:
        index_classes = [ItemImageIndex]

        fields = [
            "id",
            "text",
            "image",
            "thumbnail",
            "repository_city",
            "repository_name",
            "shelfmark",
            "locus",
            "date",
            "number_of_annotations",
            "type",
            "components",
        ]


class ImageFacetSearchSerializer(HaystackFacetSerializer):
    serialize_objects = True

    class Meta:
        fields = [
            "locus",
            "type",
            "repository_city",
            "repository_name",
            "components",
            "features",
            "component_features",
        ]
        field_options = {
            "locus": {},
            "type": {},
            "repository_city": {},
            "repository_name": {},
            "components": {},
            "features": {},
            "component_features": {},
        }


class ImageSearchViewSet(FacetMixin, HaystackViewSet):
    index_models = [ItemImage]
    serializer_class = ImageSearchSerializer
    facet_serializer_class = ImageFacetSearchSerializer
    filter_backends = [HaystackFilter, HaystackOrderingFilter]

    ordering_fields = [
        "repository_name_exact",
        "repository_city_exact",
        "shelfmark_exact",
        "type_exact",
        "number_of_annotations_exact",
    ]
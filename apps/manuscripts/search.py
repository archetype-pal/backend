from haystack.query import SQ
from rest_framework.exceptions import ValidationError

from haystack_rest.mixins import FacetMixin
from haystack_rest.serializers import HaystackFacetSerializer, HaystackSerializer
from haystack_rest.viewsets import HaystackViewSet

from .models import HistoricalItem
from .search_indexes import ItemPartIndex


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
            "issuer_name",
            "date_min",  # Add date_min for faceting
            "date_max",  # Add date_max for faceting
        ]
        field_options = {
            "image_availability": {},
            "type": {},
            "repository_city": {},
            "repository_name": {},
            "named_beneficiary": {},
            "issuer_name": {},
            "date_min": {},  # No special options needed; simple integer faceting
            "date_max": {},  # No special options needed; simple integer faceting
        }


class ManuscriptSearchViewSet(FacetMixin, HaystackViewSet):
    serializer_class = ManuscriptSearchSerializer
    facet_serializer_class = ManuscriptFacetSearchSerializer

    def filter_facet_queryset(self, queryset):
        """
        Apply additional custom filters based on at_most, at_least, and date_diff parameters.
        """
        params = self.request.query_params
        filters = {}

        # Regular date_min and date_max filtering logic
        if "date_min" in params:
            try:
                filters["date_min__gte"] = int(params["date_min"])
            except ValueError:
                raise ValidationError({"detail": "Invalid value for date_min. Must be an integer."})

        if "date_max" in params:
            try:
                filters["date_max__lte"] = int(params["date_max"])
            except ValueError:
                raise ValidationError({"detail": "Invalid value for date_max. Must be an integer."})

        # Custom handling for at_most, at_least, and date_diff
        at_most_or_least = params.get("at_most_or_least", None)
        date_diff = params.get("date_diff", None)

        if at_most_or_least and date_diff:
            try:
                # Ensure date_diff is an integer
                date_diff = int(date_diff)
            except ValueError:
                raise ValidationError({"detail": "Invalid value for date_diff. Must be an integer."})

            if at_most_or_least == "at most":
                # Filter entries where the date range is at most `date_diff`
                filters["date_max__lte"] = filters.get("date_min__gte", 0) + date_diff
            elif at_most_or_least == "at least":
                # Filter entries where the date range is at least `date_diff`
                filters["date_min__gte"] = filters.get("date_min__gte", 0)
                filters["date_max__gte"] = filters["date_min__gte"] + date_diff
            else:
                raise ValidationError(
                    {"detail": "Invalid value for at_most_or_least. Must be 'at most' or 'at least'."}
                )

        # Apply the filters to the queryset
        if filters:
            queryset = queryset.filter(**filters)

        return super().filter_facet_queryset(queryset)


# class ImageSearchSerializer(HaystackSerializer):
#     class Meta:
#         index_classes = [ItemImageIndex]

#         fields = [
#             "id",
#             "text",
#             "image",
#             "repository_city",
#             "repository_name",
#             "shelfmark",
#             "locus",
#             "date",
#             "number_of_annotations",
#             "type",
#             "issuer_name",
#             "named_beneficiary",
#         ]


# class ImageFacetSearchSerializer(HaystackFacetSerializer):

#     serialize_objects = True

#     class Meta(ImageSearchSerializer.Meta):
#         field_options = {
#             "locus": {},
#             "type": {},
#             "repository_city": {},
#             "repository_name": {},
#             "issuer_name": {},
#             "named_beneficiary": {},
#             "component": {},  # not implemented yet!
#             "feature": {},  # not implemented yet!
#         }


# class ImageSearchViewSet(FacetMixin, HaystackViewSet):
#     serializer_class = ImageSearchSerializer
#     facet_serializer_class = ImageFacetSearchSerializer

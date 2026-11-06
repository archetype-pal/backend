"""django-filter FilterSets for the manuscripts management endpoints.

The dashboard's coverage buckets ("no text at all", "no transcription",
"no translation", "empty content", "no language") are not expressible with
plain `filterset_fields`, so they are declared here as method filters. Being
real filters, they are also visible to the schema and reject bad input the
same way every other query parameter does.
"""

from django.db.models import Exists, OuterRef, QuerySet
from django_filters import rest_framework as filters

from .models import ImageText, ItemImage

# Sentinel for "the language field is the empty string": `?language=` URL-decodes
# to a blank value, which django-filter treats as "no filter".
UNSET_LANGUAGE = "__unset__"


def _has_text(queryset: QuerySet[ItemImage], value: bool, **lookups) -> QuerySet[ItemImage]:
    texts = ImageText.objects.filter(item_image_id=OuterRef("pk"), **lookups)
    return queryset.filter(Exists(texts)) if value else queryset.filter(~Exists(texts))


class ItemImageManagementFilterSet(filters.FilterSet):
    has_text = filters.BooleanFilter(method="filter_has_text", help_text="Images with (or without) any text.")
    has_transcription = filters.BooleanFilter(method="filter_has_transcription")
    has_translation = filters.BooleanFilter(method="filter_has_translation")

    class Meta:
        model = ItemImage
        fields = ["item_part"]

    def filter_has_text(self, queryset, name, value):
        return _has_text(queryset, value)

    def filter_has_transcription(self, queryset, name, value):
        return _has_text(queryset, value, type=ImageText.Type.TRANSCRIPTION)

    def filter_has_translation(self, queryset, name, value):
        return _has_text(queryset, value, type=ImageText.Type.TRANSLATION)


class ImageTextManagementFilterSet(filters.FilterSet):
    language = filters.CharFilter(
        method="filter_language",
        help_text=f"Exact language, or `{UNSET_LANGUAGE}` for texts whose language is not set.",
    )
    empty = filters.BooleanFilter(method="filter_empty", help_text="Texts with (or without) empty content.")

    class Meta:
        model = ImageText
        fields = {
            "id": ["in"],
            "item_image": ["exact"],
            "status": ["exact"],
            "type": ["exact"],
            "review_assignee": ["exact"],
        }

    def filter_language(self, queryset, name, value):
        return queryset.filter(language="" if value == UNSET_LANGUAGE else value)

    def filter_empty(self, queryset, name, value):
        return queryset.filter(content="") if value else queryset.exclude(content="")

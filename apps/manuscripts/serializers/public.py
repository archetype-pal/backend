from typing import cast

from rest_framework import serializers

from apps.manuscripts.models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDescription,
    ImageText,
    ItemImage,
    ItemPart,
    MsDescArea,
    Repository,
)


class RepositorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Repository
        fields = ["name", "label", "place", "url"]


class CurrentItemSerializer(serializers.ModelSerializer):
    repository = RepositorySerializer()

    class Meta:
        model = CurrentItem
        fields = ["repository", "shelfmark"]


class BibliographicSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BibliographicSource
        fields = ["name", "label"]


class CatalogueNumberSerializer(serializers.ModelSerializer):
    catalogue = BibliographicSourceSerializer()

    class Meta:
        model = CatalogueNumber
        fields = ["number", "url", "catalogue"]


class HistoricalItemDescriptionSerializer(serializers.ModelSerializer):
    source = BibliographicSourceSerializer()

    class Meta:
        model = HistoricalItemDescription
        fields = ["source", "content"]


class HistoricalItemSerializer(serializers.ModelSerializer):
    catalogue_numbers = CatalogueNumberSerializer(many=True)
    descriptions = HistoricalItemDescriptionSerializer(many=True)
    date_display = serializers.CharField(source="date.date", read_only=True)
    # Empty when the item has no assessment for its current date (DRF falls back to `default`).
    probable_text_date = serializers.CharField(
        source="get_date_assessment.probable_text_date", read_only=True, default=""
    )
    dating_notes = serializers.CharField(source="get_date_assessment.dating_notes", read_only=True, default="")

    class Meta:
        model = HistoricalItem
        fields = [
            "type",
            "format",
            "date",
            "date_display",
            "probable_text_date",
            "dating_notes",
            "catalogue_numbers",
            "descriptions",
        ]


class MsDescAreaSerializer(serializers.ModelSerializer):
    class Meta:
        model = MsDescArea
        fields = ["area", "content"]


class ItemPartDetailSerializer(serializers.ModelSerializer):
    current_item = CurrentItemSerializer()
    historical_item = HistoricalItemSerializer()
    msdesc_areas = serializers.SerializerMethodField()

    class Meta:
        model = ItemPart
        fields = ["id", "current_item", "historical_item", "display_label", "msdesc_areas"]

    def get_msdesc_areas(self, obj) -> list[dict]:
        # Publication gate: the public API never
        # serves unpublished areas. Filtered in Python over `.all()` so the
        # viewset's `msdesc_areas` prefetch cache is reused, not re-queried.
        published = [area for area in obj.msdesc_areas.all() if area.is_published]
        return cast(list[dict], MsDescAreaSerializer(published, many=True).data)


class ItemPartListSerializer(serializers.ModelSerializer):
    # Fields from HistoricalItem
    type = serializers.CharField(source="historical_item.type")
    format = serializers.CharField(source="historical_item.format")
    language = serializers.CharField(source="historical_item.language")
    hair_type = serializers.CharField(source="historical_item.hair_type")
    date = serializers.CharField(source="historical_item.date")
    # Fields from CurrentItem, which is optional on a part.
    repository_id = serializers.IntegerField(source="current_item.repository_id", read_only=True, allow_null=True)
    shelfmark = serializers.CharField(source="current_item.shelfmark", read_only=True, allow_null=True)

    class Meta:
        model = ItemPart
        fields = [
            "id",
            "type",
            "format",
            "language",
            "hair_type",
            "date",
            "repository_id",
            "shelfmark",
            "display_label",
        ]


class ImageTextSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageText
        fields = ["type", "content", "language"]


class ImageTextDetailSerializer(ImageTextSerializer):
    class Meta(ImageTextSerializer.Meta):
        fields = ["id", "item_image", *ImageTextSerializer.Meta.fields, "status", "created", "modified"]


class ImageSerializer(serializers.ModelSerializer):
    texts = ImageTextSerializer(many=True)
    iiif_image = serializers.URLField(source="image.iiif.identifier")
    # Annotated by `ImageViewSet` so a list costs no per-row COUNT.
    number_of_annotations = serializers.IntegerField(source="annotation_count", read_only=True)
    number_of_image_annotations = serializers.IntegerField(source="image_annotation_count", read_only=True)

    class Meta:
        model = ItemImage
        fields = [
            "id",
            "iiif_image",
            "locus",
            "number_of_annotations",
            "number_of_image_annotations",
            "texts",
            "item_part",
        ]

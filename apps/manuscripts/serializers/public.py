from rest_framework import serializers

from apps.manuscripts.models import (
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


class CatalogueNumberSerializer(serializers.ModelSerializer):
    catalogue = RepositorySerializer()

    class Meta:
        model = CatalogueNumber
        fields = ["number", "url", "catalogue"]


class HistoricalItemDescriptionSerializer(serializers.ModelSerializer):
    source = RepositorySerializer()

    class Meta:
        model = HistoricalItemDescription
        fields = ["source", "content"]


class HistoricalItemSerializer(serializers.ModelSerializer):
    catalogue_numbers = CatalogueNumberSerializer(many=True)
    descriptions = HistoricalItemDescriptionSerializer(many=True)
    date_display = serializers.CharField(source="date.date", read_only=True)
    probable_text_date = serializers.SerializerMethodField()
    dating_notes = serializers.SerializerMethodField()

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

    def get_probable_text_date(self, obj) -> str:
        assessment = obj.get_date_assessment()
        return assessment.probable_text_date if assessment else ""

    def get_dating_notes(self, obj) -> str:
        assessment = obj.get_date_assessment()
        return assessment.dating_notes if assessment else ""


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
        # Publication gate (TEI-descriptions 0.1/1.4): the public API never
        # serves unpublished areas. Filtered in Python over `.all()` so the
        # viewset's `msdesc_areas` prefetch cache is reused, not re-queried.
        published = [area for area in obj.msdesc_areas.all() if area.is_published]
        return MsDescAreaSerializer(published, many=True).data


class ItemPartListSerializer(serializers.ModelSerializer):
    # Fields from HistoricalItem
    type = serializers.CharField(source="historical_item.type")
    format = serializers.CharField(source="historical_item.format")
    language = serializers.CharField(source="historical_item.language")
    hair_type = serializers.CharField(source="historical_item.hair_type")
    date = serializers.CharField(source="historical_item.date")
    # Fields from CurrentItem
    repository_id = serializers.IntegerField(source="current_item.repository_id")
    shelfmark = serializers.CharField(source="current_item.shelfmark")

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
        fields = ["type", "content"]


class ImageTextDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageText
        fields = [
            "id",
            "item_image",
            "type",
            "content",
            "status",
            "language",
            "created",
            "modified",
        ]


class ImageSerializer(serializers.ModelSerializer):
    texts = ImageTextSerializer(many=True)
    iiif_image = serializers.URLField(source="image.iiif.identifier")
    # Read from the annotated queryset field on `ImageViewSet` to avoid an
    # N+1; falls back to the model method when this serializer is used with
    # an unannotated queryset (e.g. ad-hoc `ImageSerializer(image).data`).
    number_of_annotations = serializers.SerializerMethodField()
    number_of_image_annotations = serializers.SerializerMethodField()

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

    def get_number_of_annotations(self, obj):
        annotated = getattr(obj, "annotation_count", None)
        if annotated is not None:
            return annotated
        return obj.number_of_annotations()

    def get_number_of_image_annotations(self, obj):
        annotated = getattr(obj, "image_annotation_count", None)
        if annotated is not None:
            return annotated
        return obj.number_of_image_annotations()

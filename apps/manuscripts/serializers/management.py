from rest_framework import serializers

from apps.manuscripts.models import (
    BibliographicSource,
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDescription,
    ImageText,
    ItemFormat,
    ItemImage,
    ItemPart,
    Repository,
)
from apps.manuscripts.services import build_item_parts_detail


class RepositoryManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repository
        fields = ["id", "name", "label", "place", "url", "type"]


class BibliographicSourceManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = BibliographicSource
        fields = ["id", "name", "label"]


class ItemFormatManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemFormat
        fields = ["id", "name"]


class CurrentItemManagementSerializer(serializers.ModelSerializer):
    repository_name = serializers.CharField(source="repository.label", read_only=True)
    part_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = CurrentItem
        fields = ["id", "description", "repository", "repository_name", "shelfmark", "part_count"]


class ImageTextManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImageText
        fields = [
            "id",
            "item_image",
            "content",
            "type",
            "status",
            "language",
            "created",
            "modified",
        ]
        read_only_fields = ["created", "modified"]


class ItemImageManagementSerializer(serializers.ModelSerializer):
    texts = ImageTextManagementSerializer(many=True, read_only=True)
    annotation_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ItemImage
        fields = ["id", "item_part", "image", "locus", "texts", "annotation_count"]


class CatalogueNumberManagementSerializer(serializers.ModelSerializer):
    catalogue_label = serializers.CharField(source="catalogue.label", read_only=True)

    class Meta:
        model = CatalogueNumber
        fields = ["id", "historical_item", "number", "catalogue", "catalogue_label", "url"]


class HistoricalItemDescriptionManagementSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source="source.label", read_only=True)

    class Meta:
        model = HistoricalItemDescription
        fields = ["id", "historical_item", "source", "source_label", "content"]


class ItemPartManagementSerializer(serializers.ModelSerializer):
    display_label = serializers.CharField(read_only=True)
    current_item_display = serializers.CharField(source="current_item", read_only=True)
    image_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ItemPart
        fields = [
            "id",
            "historical_item",
            "custom_label",
            "current_item",
            "current_item_display",
            "current_item_locus",
            "display_label",
            "image_count",
        ]


class HistoricalItemListManagementSerializer(serializers.ModelSerializer):
    catalogue_numbers_display = serializers.CharField(source="get_catalogue_numbers_display", read_only=True)
    date_display = serializers.StringRelatedField(source="date", read_only=True)
    format_display = serializers.StringRelatedField(source="format", read_only=True)
    part_count = serializers.IntegerField(read_only=True)
    location_display = serializers.SerializerMethodField()
    repository_label = serializers.SerializerMethodField()
    shelfmark = serializers.SerializerMethodField()
    image_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = HistoricalItem
        fields = [
            "id",
            "type",
            "format",
            "format_display",
            "language",
            "hair_type",
            "date",
            "date_display",
            "catalogue_numbers_display",
            "part_count",
            "location_display",
            "repository_label",
            "shelfmark",
            "image_count",
        ]

    def _first_current_item(self, obj):
        for part in obj.itempart_set.all():
            if part.current_item_id:
                return part.current_item
        return None

    def get_location_display(self, obj):
        current_item = self._first_current_item(obj)
        if current_item:
            return str(current_item)
        return None

    def get_repository_label(self, obj):
        current_item = self._first_current_item(obj)
        if current_item and current_item.repository:
            return current_item.repository.label
        return None

    def get_shelfmark(self, obj):
        current_item = self._first_current_item(obj)
        if current_item:
            return current_item.shelfmark
        return None


class HistoricalItemDetailManagementSerializer(serializers.ModelSerializer):
    catalogue_numbers = CatalogueNumberManagementSerializer(many=True, read_only=True)
    descriptions = HistoricalItemDescriptionManagementSerializer(many=True, read_only=True)
    item_parts = serializers.SerializerMethodField()
    date_display = serializers.StringRelatedField(source="date", read_only=True)
    format_display = serializers.StringRelatedField(source="format", read_only=True)

    class Meta:
        model = HistoricalItem
        fields = [
            "id",
            "type",
            "format",
            "format_display",
            "language",
            "hair_type",
            "date",
            "date_display",
            "catalogue_numbers",
            "descriptions",
            "item_parts",
        ]

    def get_item_parts(self, historical_item):
        return build_item_parts_detail(historical_item)


class HistoricalItemWriteManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricalItem
        fields = ["id", "type", "format", "language", "hair_type", "date"]

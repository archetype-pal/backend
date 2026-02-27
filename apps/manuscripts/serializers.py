import logging

from rest_framework import serializers

from .models import (
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

logger = logging.getLogger(__name__)


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

    class Meta:
        model = HistoricalItem
        fields = [
            "type",
            "format",
            "date",
            "catalogue_numbers",
            "descriptions",
            # "language",
            # "hair_type",
        ]


class ItemPartDetailSerializer(serializers.ModelSerializer):
    current_item = CurrentItemSerializer()
    historical_item = HistoricalItemSerializer()

    class Meta:
        model = ItemPart
        fields = ["id", "current_item", "historical_item", "display_label"]


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


class ImageSerializer(serializers.ModelSerializer):
    texts = ImageTextSerializer(many=True)
    iiif_image = serializers.URLField(source="image.iiif.identifier")

    class Meta:
        model = ItemImage
        fields = ["id", "iiif_image", "locus", "number_of_annotations", "texts", "item_part"]


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
    part_count = serializers.IntegerField(source="itempart_set.count", read_only=True)

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
    annotation_count = serializers.IntegerField(source="graphs.count", read_only=True)

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
    image_count = serializers.IntegerField(source="images.count", read_only=True)

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
    part_count = serializers.IntegerField(source="itempart_set.count", read_only=True)
    location_display = serializers.SerializerMethodField()
    repository_label = serializers.SerializerMethodField()
    shelfmark = serializers.SerializerMethodField()
    image_count = serializers.SerializerMethodField()

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

    def get_image_count(self, obj):
        count = 0
        for part in obj.itempart_set.all():
            count += part.images.count()
        return count


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
        parts = (
            historical_item.itempart_set.select_related("current_item__repository")
            .prefetch_related("images__texts")
            .all()
        )
        result = []
        for part in parts:
            images = []
            for img in part.images.all():
                iiif_url = None
                if img.image:
                    try:
                        iiif_url = img.image.iiif.identifier
                    except (AttributeError, TypeError, ValueError) as exc:
                        logger.debug("IIIF identifier unavailable for image %s: %s", img.id, exc)
                        iiif_url = str(img.image)
                images.append(
                    {
                        "id": img.id,
                        "image": iiif_url,
                        "locus": img.locus,
                        "text_count": img.texts.count(),
                    }
                )
            current_item = part.current_item
            result.append(
                {
                    "id": part.id,
                    "custom_label": part.custom_label,
                    "current_item": part.current_item_id,
                    "current_item_display": str(current_item) if current_item else None,
                    "current_item_locus": part.current_item_locus,
                    "display_label": part.display_label(),
                    "repository": current_item.repository_id if current_item else None,
                    "repository_name": current_item.repository.label
                    if current_item and current_item.repository
                    else None,
                    "shelfmark": current_item.shelfmark if current_item else None,
                    "images": images,
                }
            )
        return result


class HistoricalItemWriteManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = HistoricalItem
        fields = ["id", "type", "format", "language", "hair_type", "date"]

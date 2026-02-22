import logging

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

logger = logging.getLogger(__name__)


# ── Flat CRUD serializers ──────────────────────────────────────────────


class RepositoryAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repository
        fields = ["id", "name", "label", "place", "url", "type"]


class BibliographicSourceAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = BibliographicSource
        fields = ["id", "name", "label"]


class ItemFormatAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemFormat
        fields = ["id", "name"]


class CurrentItemAdminSerializer(serializers.ModelSerializer):
    repository_name = serializers.CharField(source="repository.label", read_only=True)
    part_count = serializers.IntegerField(source="itempart_set.count", read_only=True)

    class Meta:
        model = CurrentItem
        fields = ["id", "description", "repository", "repository_name", "shelfmark", "part_count"]


class ImageTextAdminSerializer(serializers.ModelSerializer):
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


class ItemImageAdminSerializer(serializers.ModelSerializer):
    texts = ImageTextAdminSerializer(many=True, read_only=True)
    annotation_count = serializers.IntegerField(
        source="graphs.count", read_only=True
    )

    class Meta:
        model = ItemImage
        fields = ["id", "item_part", "image", "locus", "texts", "annotation_count"]


class CatalogueNumberAdminSerializer(serializers.ModelSerializer):
    catalogue_label = serializers.CharField(source="catalogue.label", read_only=True)

    class Meta:
        model = CatalogueNumber
        fields = ["id", "historical_item", "number", "catalogue", "catalogue_label", "url"]


class HistoricalItemDescriptionAdminSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source="source.label", read_only=True)

    class Meta:
        model = HistoricalItemDescription
        fields = ["id", "historical_item", "source", "source_label", "content"]


class ItemPartAdminSerializer(serializers.ModelSerializer):
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


class HistoricalItemListAdminSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    catalogue_numbers_display = serializers.CharField(
        source="get_catalogue_numbers_display", read_only=True
    )
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
        """Return the CurrentItem from the first ItemPart that has one."""
        for part in obj.itempart_set.all():
            if part.current_item_id:
                return part.current_item
        return None

    def get_location_display(self, obj):
        ci = self._first_current_item(obj)
        if ci:
            return str(ci)
        return None

    def get_repository_label(self, obj):
        ci = self._first_current_item(obj)
        if ci and ci.repository:
            return ci.repository.label
        return None

    def get_shelfmark(self, obj):
        ci = self._first_current_item(obj)
        if ci:
            return ci.shelfmark
        return None

    def get_image_count(self, obj):
        count = 0
        for part in obj.itempart_set.all():
            count += part.images.count()
        return count


class HistoricalItemDetailAdminSerializer(serializers.ModelSerializer):
    """
    Detailed read serializer that nests item_parts, catalogue_numbers,
    and descriptions for the unified manuscript workspace.
    """

    catalogue_numbers = CatalogueNumberAdminSerializer(many=True, read_only=True)
    descriptions = HistoricalItemDescriptionAdminSerializer(many=True, read_only=True)
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
        parts = historical_item.itempart_set.select_related(
            "current_item__repository",
        ).prefetch_related("images__texts").all()
        result = []
        for part in parts:
            images = []
            for img in part.images.all():
                iiif_url = None
                if img.image:
                    try:
                        iiif_url = img.image.iiif.identifier
                    except (AttributeError, TypeError, ValueError) as e:
                        logger.debug("IIIF identifier unavailable for image %s: %s", img.id, e)
                        iiif_url = str(img.image)
                images.append(
                    {
                        "id": img.id,
                        "image": iiif_url,
                        "locus": img.locus,
                        "text_count": img.texts.count(),
                    }
                )
            ci = part.current_item
            result.append(
                {
                    "id": part.id,
                    "custom_label": part.custom_label,
                    "current_item": part.current_item_id,
                    "current_item_display": str(ci) if ci else None,
                    "current_item_locus": part.current_item_locus,
                    "display_label": part.display_label(),
                    "repository": ci.repository_id if ci else None,
                    "repository_name": ci.repository.label if ci and ci.repository else None,
                    "shelfmark": ci.shelfmark if ci else None,
                    "images": images,
                }
            )
        return result


class HistoricalItemWriteAdminSerializer(serializers.ModelSerializer):
    """Write serializer for creating/updating HistoricalItem top-level fields."""

    class Meta:
        model = HistoricalItem
        fields = ["id", "type", "format", "language", "hair_type", "date"]

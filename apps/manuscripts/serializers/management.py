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
    StatusTransition,
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
    review_assignee_username = serializers.CharField(source="review_assignee.username", read_only=True, default=None)
    last_transition = serializers.SerializerMethodField()
    # Display context for the list UI — `item_image` itself is only an FK id,
    # so the dashboard would have to fan out one fetch per row to render a
    # human label. These cheap select_related fields short-circuit that.
    item_part_id = serializers.IntegerField(source="item_image.item_part_id", read_only=True)
    item_image_locus = serializers.CharField(source="item_image.locus", read_only=True, default="")
    item_image_label = serializers.SerializerMethodField()
    char_count = serializers.SerializerMethodField()
    is_empty = serializers.SerializerMethodField()

    class Meta:
        model = ImageText
        fields = [
            "id",
            "item_image",
            "item_part_id",
            "item_image_locus",
            "item_image_label",
            "content",
            "char_count",
            "is_empty",
            "type",
            "status",
            "language",
            "review_assignee",
            "review_assignee_username",
            "last_transition",
            "created",
            "modified",
        ]
        read_only_fields = [
            "created",
            "modified",
            "last_transition",
            "review_assignee_username",
            "item_part_id",
            "item_image_locus",
            "item_image_label",
            "char_count",
            "is_empty",
        ]

    def get_last_transition(self, obj) -> dict | None:
        last = obj.status_transitions.first() if hasattr(obj, "status_transitions") else None
        if not last:
            return None
        return {
            "id": last.id,
            "from_status": last.from_status,
            "to_status": last.to_status,
            "actor": last.actor_id,
            "actor_username": last.actor.username if last.actor_id else None,
            "note": last.note,
            "created": last.created.isoformat(),
        }

    def get_item_image_label(self, obj) -> str:
        return str(obj.item_image) if obj.item_image_id else ""

    def get_char_count(self, obj) -> int:
        return len(obj.content or "")

    def get_is_empty(self, obj) -> bool:
        return not obj.content


class StatusTransitionSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = StatusTransition
        fields = ["id", "from_status", "to_status", "actor", "actor_username", "note", "created"]
        read_only_fields = fields


class ItemImageManagementSerializer(serializers.ModelSerializer):
    texts = ImageTextManagementSerializer(many=True, read_only=True)
    annotation_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ItemImage
        fields = ["id", "item_part", "image", "locus", "tags", "texts", "annotation_count"]


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

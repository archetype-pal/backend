from rest_framework import serializers

from apps.manuscripts.models import (
    CatalogueNumber,
    CurrentItem,
    HistoricalItem,
    HistoricalItemDateAssessment,
    HistoricalItemDescription,
    ItemFormat,
    ItemImage,
    ItemPart,
    StatusTransition,
)
from apps.manuscripts.services.iiif import get_image_identifier
from apps.manuscripts.services.images import hand_attribution_error

from .public import (
    BibliographicSourceSerializer,
    ImageTextDetailSerializer,
    MsDescAreaSerializer,
    RepositorySerializer,
)


class RepositoryManagementSerializer(RepositorySerializer):
    current_item_count = serializers.IntegerField(read_only=True)

    class Meta(RepositorySerializer.Meta):
        fields = ["id", *RepositorySerializer.Meta.fields, "type", "current_item_count"]


class BibliographicSourceManagementSerializer(BibliographicSourceSerializer):
    class Meta(BibliographicSourceSerializer.Meta):
        fields = ["id", *BibliographicSourceSerializer.Meta.fields]


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


class StatusTransitionSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True, default=None)

    class Meta:
        model = StatusTransition
        fields = ["id", "from_status", "to_status", "actor", "actor_username", "note", "created"]
        read_only_fields = fields


class ImageTextManagementSerializer(ImageTextDetailSerializer):
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

    class Meta(ImageTextDetailSerializer.Meta):
        fields = [
            *ImageTextDetailSerializer.Meta.fields,
            "item_part_id",
            "item_image_locus",
            "item_image_label",
            "char_count",
            "is_empty",
            "review_assignee",
            "review_assignee_username",
            "last_transition",
        ]
        read_only_fields = ["created", "modified"]

    def get_last_transition(self, obj) -> dict | None:
        # Use the prefetched, actor-joined transitions when the viewset supplied
        # them (avoids an N+1); otherwise fall back to a single query.
        prefetched = getattr(obj, "_prefetched_objects_cache", {}).get("status_transitions")
        if prefetched is not None:
            last = prefetched[0] if prefetched else None
        else:
            last = obj.status_transitions.first() if hasattr(obj, "status_transitions") else None
        return StatusTransitionSerializer(last).data if last else None

    def validate_item_image(self, value):
        # Its region links point at graphs on this image only.
        if self.instance is not None and value.pk != self.instance.item_image_id:
            raise serializers.ValidationError("A text cannot be moved to another image.")
        return value

    def get_item_image_label(self, obj) -> str:
        return str(obj.item_image) if obj.item_image_id else ""

    def get_char_count(self, obj) -> int:
        return len(obj.content or "")

    def get_is_empty(self, obj) -> bool:
        return not obj.content


class ImagePathField(serializers.CharField):
    """`ItemImage.image`: takes a storage-relative path, returns a IIIF identifier.

    The model field is an ImageField subclass, so DRF's default mapping was a
    binary file field that 400'd the backoffice's JSON path edits. Writes take
    ONLY a path string. Raw bytes are refused here because an unconverted file
    would recreate issue #114: images have to be converted to JP2 before a row
    is pointed at them.

    Reads return the IIIF identifier, not the stored path, because every
    consumer of this field renders a thumbnail from it and the identifier is
    the only form the image server is addressable by — see
    `apps.manuscripts.services.iiif.get_image_identifier`. The two shapes are
    deliberately asymmetric, so the value read back here cannot be PATCHed
    straight in again; `to_internal_value` rejects it rather than storing a URL
    where a path belongs, which would break the literal-path lookup.
    """

    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError(
                "Provide a storage-relative path string; this field does not accept file uploads."
            )
        value = data.strip().lstrip("/")
        if not value:
            raise serializers.ValidationError("Image path cannot be empty.")
        if "://" in value:
            raise serializers.ValidationError(
                "Provide a storage-relative path, not a URL. This field returns a IIIF "
                "identifier, which cannot be sent back unchanged."
            )
        if ".." in value.split("/"):
            raise serializers.ValidationError("Image path may not contain '..'.")
        return super().to_internal_value(value)

    def to_representation(self, value):
        return get_image_identifier(value)


class TagListField(serializers.ListField):
    """Serializes `ItemImage.tags` (a Tagulous TagField / ManyToManyField) as a
    list of tag names.

    DRF's default `ModelSerializer` mapping produces `PrimaryKeyRelatedField
    (many=True)`, expecting Tag primary keys — wrong for free-text tag editing,
    and it 400s ("not_a_list") on any non-list input, including the plain
    string the backoffice used to send.

    No `create`/`update` override is needed: `TagField` is structurally a real
    `ManyToManyField`, so DRF's `model_meta` classifies `tags` as a to-many
    relation and the stock `ModelSerializer.create()`/`update()` already call
    `instance.tags.set(validated_data["tags"])` — and Tagulous's own manager
    (`TagRelatedManagerMixin.add()`) accepts plain tag-name strings directly,
    creating/looking up `Tag` rows itself.

    `force_lowercase=True` on the model field is only honored by the separate
    string-assignment path (`instance.tags = "a, b"`), not by `.set()`/`.add()`,
    so it's applied explicitly here.
    """

    # Bounded to the tag model's own `name` column (Tagulous's
    # TAGULOUS_NAME_MAX_LENGTH, 255 by default). Unbounded, an over-long name
    # passes validation and Tagulous's manager writes it straight through
    # get_or_create, which is a 500 on Postgres. SQLite ignores the declared
    # length, so a test database can't catch this on its own.
    child = serializers.CharField(max_length=255)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)  # matches the model field's blank=True
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        tag_names = super().to_internal_value(data)
        # Dedupe (order-preserving): Tagulous's manager only filters out tags
        # already on the instance, not duplicates within this list, so
        # "Damaged, damaged" would otherwise double-increment that Tag's
        # usage count for a single actual relation.
        return list(dict.fromkeys(name.strip().lower() for name in tag_names))

    def to_representation(self, value):
        # A plain ListField doesn't auto-resolve a manager the way
        # ManyRelatedField does — same shape already used for this field in
        # apps/search/documents/item_images.py.
        return [tag.name for tag in value.all()]


class ItemImageManagementSerializer(serializers.ModelSerializer):
    texts = ImageTextManagementSerializer(many=True, read_only=True)
    annotation_count = serializers.IntegerField(read_only=True)
    image = ImagePathField(max_length=200)
    tags = TagListField()

    class Meta:
        model = ItemImage
        fields = ["id", "item_part", "image", "locus", "tags", "texts", "annotation_count"]

    def validate_item_part(self, value):
        image = self.instance
        if image is not None and value.pk != image.item_part_id and (error := hand_attribution_error(image)):
            raise serializers.ValidationError(error)
        return value


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


class MsDescAreaManagementSerializer(MsDescAreaSerializer):
    class Meta(MsDescAreaSerializer.Meta):
        fields = ["id", "item_part", *MsDescAreaSerializer.Meta.fields, "is_published"]


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
    """List row; `repository_label` / `shelfmark` are the queryset's sort-key annotations
    (`optimize_historical_item_management_queryset`), so what is shown is what is sorted."""

    catalogue_numbers_display = serializers.CharField(source="get_catalogue_numbers_display", read_only=True)
    date_display = serializers.StringRelatedField(source="date", read_only=True)
    format_display = serializers.StringRelatedField(source="format", read_only=True)
    part_count = serializers.IntegerField(read_only=True)
    location_display = serializers.SerializerMethodField()
    repository_label = serializers.CharField(source="first_repository_label", read_only=True)
    shelfmark = serializers.CharField(source="first_shelfmark", read_only=True)
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

    def get_location_display(self, obj) -> str | None:
        # `str(CurrentItem)`, from the annotations; None when no part has a current item.
        if obj.first_repository_label is None:
            return None
        return f"{obj.first_repository_label} {obj.first_shelfmark}"


class ItemPartWorkspaceImageSerializer(serializers.ModelSerializer):
    """An image as the historical-item workspace lists it, inside its part."""

    image = ImagePathField(read_only=True)
    # Bare storage-relative path, the shape ImagePathField accepts on write —
    # `image` is the IIIF identifier thumbnails need, not a path a person
    # editing this row would recognize or compare.
    image_path = serializers.SerializerMethodField()
    tags = TagListField(read_only=True)
    text_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ItemImage
        fields = ["id", "image", "image_path", "locus", "tags", "text_count"]

    def get_image_path(self, obj) -> str | None:
        return obj.image.name if obj.image else None


class ItemPartWorkspaceSerializer(serializers.ModelSerializer):
    """A part with its images and msDesc areas, nested in the historical-item detail payload.

    Unpublished areas are included: this is the editing workspace, and the
    public serializer owns the `is_published` gate.
    """

    current_item_display = serializers.StringRelatedField(source="current_item", read_only=True)
    display_label = serializers.CharField(read_only=True)
    repository = serializers.IntegerField(source="current_item.repository_id", read_only=True, allow_null=True)
    repository_name = serializers.CharField(source="current_item.repository.label", read_only=True, allow_null=True)
    shelfmark = serializers.CharField(source="current_item.shelfmark", read_only=True, allow_null=True)
    images = ItemPartWorkspaceImageSerializer(many=True, read_only=True)
    msdesc_areas = MsDescAreaManagementSerializer(many=True, read_only=True)

    class Meta:
        model = ItemPart
        fields = [
            "id",
            "custom_label",
            "current_item",
            "current_item_display",
            "current_item_locus",
            "display_label",
            "repository",
            "repository_name",
            "shelfmark",
            "images",
            "msdesc_areas",
        ]


class HistoricalItemDetailManagementSerializer(serializers.ModelSerializer):
    catalogue_numbers = CatalogueNumberManagementSerializer(many=True, read_only=True)
    descriptions = HistoricalItemDescriptionManagementSerializer(many=True, read_only=True)
    # See `optimize_historical_item_management_queryset` for the prefetch this reads.
    item_parts = ItemPartWorkspaceSerializer(source="itempart_set", many=True, read_only=True)
    date_display = serializers.StringRelatedField(source="date", read_only=True)
    format_display = serializers.StringRelatedField(source="format", read_only=True)
    probable_text_date = serializers.CharField(
        source="get_date_assessment.probable_text_date", read_only=True, default=""
    )
    dating_notes = serializers.CharField(source="get_date_assessment.dating_notes", read_only=True, default="")

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
            "probable_text_date",
            "dating_notes",
            "catalogue_numbers",
            "descriptions",
            "item_parts",
        ]


class HistoricalItemWriteManagementSerializer(serializers.ModelSerializer):
    probable_text_date = serializers.CharField(required=False, allow_blank=True, write_only=True)
    dating_notes = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = HistoricalItem
        fields = ["id", "type", "format", "language", "hair_type", "date", "probable_text_date", "dating_notes"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        date = attrs.get("date", self.instance.date if self.instance else None)
        probable_text_date = attrs.get("probable_text_date")
        dating_notes = attrs.get("dating_notes")
        if date is None and (
            (probable_text_date is not None and probable_text_date) or (dating_notes is not None and dating_notes)
        ):
            raise serializers.ValidationError(
                {
                    "date": "A historical item date is required before date assessment fields can be saved.",
                }
            )
        return attrs

    def create(self, validated_data):
        assessment_data = self._pop_assessment_data(validated_data)
        historical_item = super().create(validated_data)
        self._sync_date_assessment(historical_item, assessment_data)
        return historical_item

    def update(self, instance, validated_data):
        old_date_id = instance.date_id
        assessment_data = self._pop_assessment_data(validated_data)
        historical_item = super().update(instance, validated_data)
        if old_date_id != historical_item.date_id:
            historical_item.date_assessments.exclude(date_id=historical_item.date_id).delete()
        self._sync_date_assessment(historical_item, assessment_data)
        return historical_item

    def _pop_assessment_data(self, validated_data) -> dict[str, str]:
        assessment_data: dict[str, str] = {}
        for field in ("probable_text_date", "dating_notes"):
            if field in validated_data:
                assessment_data[field] = validated_data.pop(field)
        return assessment_data

    def _sync_date_assessment(self, historical_item, assessment_data: dict[str, str]) -> None:
        if not assessment_data:
            return

        if not historical_item.date_id:
            return

        assessment = historical_item.get_date_assessment()
        probable_text_date = assessment_data.get(
            "probable_text_date",
            assessment.probable_text_date if assessment else "",
        )
        dating_notes = assessment_data.get(
            "dating_notes",
            assessment.dating_notes if assessment else "",
        )

        if not probable_text_date and not dating_notes:
            if assessment:
                assessment.delete()
            return

        HistoricalItemDateAssessment.objects.update_or_create(
            historical_item=historical_item,
            date_id=historical_item.date_id,
            defaults={
                "probable_text_date": probable_text_date,
                "dating_notes": dating_notes,
            },
        )

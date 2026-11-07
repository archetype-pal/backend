from rest_framework import serializers

from apps.diplomatic import services
from apps.diplomatic.pipelines.extraction import plain_text

from .models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation


class ProposalSourceSerializer(serializers.Serializer):
    """The charter a proposal was read from: enough to find it and to judge against it."""

    image_text = serializers.IntegerField(source="pk")
    type = serializers.CharField()
    item_image = serializers.IntegerField(source="item_image_id")
    # The viewer's route is the part and the image: /manuscripts/<part>/images/<image>.
    item_part = serializers.IntegerField(source="item_image.item_part_id")
    historical_item = serializers.IntegerField(source="item_image.item_part.historical_item_id")
    label = serializers.CharField(source="item_image")
    # The catalogue date, which is what W3.2's verdict was judged against.
    date = serializers.CharField(source="item_image.item_part.historical_item.date.date", default="")


class ProposalSerializer(serializers.ModelSerializer):
    """A queue row: what was proposed, about which charter, by which model.

    A list reads its sources through the `sources` context its view builds for
    the whole page (`services.proposal_sources`); a single row fetches its own.
    """

    reviewer_username = serializers.CharField(source="reviewer.username", read_only=True, default="")
    model_name = serializers.CharField(source="ml_job.model_name", read_only=True, default="")
    source = serializers.SerializerMethodField()

    class Meta:
        model = Proposal
        fields: tuple[str, ...] = (
            "id",
            "pipeline",
            "source_type",
            "source_id",
            "source",
            "payload",
            "confidence",
            "ml_job",
            "model_name",
            "status",
            "reviewer",
            "reviewer_username",
            "reviewed",
            "reason",
            "dropped_items",
            "created",
        )
        # Everything but the reason is machine-written or set by the decision
        # endpoints. A proposal that could be edited before acceptance would let
        # a reviewer launder their own text as a model's.
        read_only_fields: tuple[str, ...] = fields

    def _source(self, obj):
        sources = self.context.get("sources")
        if sources is None:
            sources = services.proposal_sources([obj])
        return sources.get(obj.source_id) if obj.source_type == services.SOURCE_IMAGETEXT else None

    def get_source(self, obj) -> dict | None:
        text = self._source(obj)
        return ProposalSourceSerializer(text).data if text else None


class ProposalDetailSerializer(ProposalSerializer):
    """A row plus the charter text the model read, for checking it word by word."""

    source_text = serializers.SerializerMethodField()

    class Meta(ProposalSerializer.Meta):
        fields = (*ProposalSerializer.Meta.fields, "source_text")
        read_only_fields = fields

    def get_source_text(self, obj) -> str:
        # The same stripping the pipelines applied, so the reviewer sees what
        # the model saw.
        text = self._source(obj)
        return plain_text(text.content) if text else ""


class AcceptSerializer(serializers.Serializer):
    # Positions in the proposal's list to record; left out, the whole answer is.
    items = serializers.ListField(child=serializers.IntegerField(min_value=0), required=False)


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


# What a public record needs to name its charter and open it, read in the same
# query as the record. The views select these paths for every record they serve.
CHARTER_PATHS = (
    "image_text__item_image__item_part__current_item__repository",
    "image_text__item_image__item_part__historical_item__date",
)


class CharterSerializer(serializers.Serializer):
    """The text a public record came from: its name, its date, and the viewer's route to it."""

    image_text = serializers.IntegerField(source="pk")
    type = serializers.CharField()
    item_image = serializers.IntegerField(source="item_image_id")
    item_part = serializers.IntegerField(source="item_image.item_part_id")
    locus = serializers.CharField(source="item_image.locus")
    shelfmark = serializers.SerializerMethodField()
    repository = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()

    def get_shelfmark(self, obj) -> str:
        current = obj.item_image.item_part.current_item
        return current.shelfmark if current else ""

    def get_repository(self, obj) -> str:
        current = obj.item_image.item_part.current_item
        return current.repository.name if current and current.repository_id else ""

    def get_date(self, obj) -> str:
        item = obj.item_image.item_part.historical_item
        return item.date.date if item and item.date_id else ""


class CharterEntitySerializer(serializers.ModelSerializer):
    charter = CharterSerializer(source="image_text", read_only=True)

    class Meta:
        model = CharterEntity
        fields = ("id", "image_text", "charter", "role", "name", "normalised", "note", "proposal", "created")


class FormulaOccurrenceSerializer(serializers.ModelSerializer):
    charter = CharterSerializer(source="image_text", read_only=True)

    class Meta:
        model = FormulaOccurrence
        fields = ("id", "image_text", "charter", "excerpt")


class FormulaSerializer(serializers.ModelSerializer):
    occurrences = FormulaOccurrenceSerializer(many=True, read_only=True)
    occurrence_count = serializers.IntegerField(source="occurrences.count", read_only=True)
    exemplar = serializers.SerializerMethodField()

    class Meta:
        model = Formula
        fields = (
            "id",
            "kind",
            "label",
            "exemplar",
            "published_type",
            "occurrence_count",
            "occurrences",
            "created",
        )

    def get_exemplar(self, formula: Formula) -> str:
        # The stored exemplar is the wording of whichever charter was accepted
        # first, which may be a draft this reader may not see. `occurrences` is
        # already limited to what they may.
        return next((row.excerpt for row in formula.occurrences.all() if row.excerpt), "")


class RelationSerializer(serializers.ModelSerializer):
    charter = CharterSerializer(source="image_text", read_only=True)

    class Meta:
        model = Relation
        fields = ("id", "image_text", "charter", "subject", "predicate", "object", "proposal", "created")

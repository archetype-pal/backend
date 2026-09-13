from rest_framework import serializers

from .models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation


class ProposalListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Proposal
        fields = ("id", "pipeline", "source_type", "source_id", "status", "confidence", "created")


class ProposalSerializer(serializers.ModelSerializer):
    reviewer_username = serializers.CharField(source="reviewer.username", read_only=True, default="")

    class Meta:
        model = Proposal
        fields = (
            "id",
            "pipeline",
            "source_type",
            "source_id",
            "payload",
            "confidence",
            "ml_job",
            "status",
            "reviewer",
            "reviewer_username",
            "reviewed",
            "reason",
            "created",
        )
        # Everything but the reason is machine-written or set by the decision
        # endpoints. A proposal that could be edited before acceptance would let
        # a reviewer launder their own text as a model's.
        read_only_fields = fields


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class CharterEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = CharterEntity
        fields = ("id", "image_text", "role", "name", "normalised", "note", "proposal", "created")


class FormulaOccurrenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormulaOccurrence
        fields = ("id", "image_text", "excerpt")


class FormulaSerializer(serializers.ModelSerializer):
    occurrences = FormulaOccurrenceSerializer(many=True, read_only=True)
    occurrence_count = serializers.IntegerField(source="occurrences.count", read_only=True)

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


class RelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Relation
        fields = ("id", "image_text", "subject", "predicate", "object", "proposal", "created")

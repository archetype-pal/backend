from rest_framework import serializers

from apps.symbols_structure.models import Allograph

from .models import Hand, HandDescription, Scribe, Script
from .services import get_scribe_idiographs


class HandDescriptionSerializer(serializers.ModelSerializer):
    """Public shape: just the source's citation label, not the full row."""

    source_label = serializers.CharField(source="source.label", read_only=True, default=None)

    class Meta:
        model = HandDescription
        fields = ["id", "source_label", "content"]


class IdiographSerializer(serializers.ModelSerializer):
    character = serializers.StringRelatedField()

    class Meta:
        model = Allograph
        fields = ["id", "name", "character"]


class ScribeSerializer(serializers.ModelSerializer):
    idiographs = serializers.SerializerMethodField()

    class Meta:
        model = Scribe
        fields = ["id", "name", "period", "scriptorium", "idiographs"]

    def get_idiographs(self, instance):
        allographs = get_scribe_idiographs(instance)
        return IdiographSerializer(allographs, many=True).data


class HandSerializer(serializers.ModelSerializer):
    scriptorium = serializers.CharField(source="scribe.scriptorium", read_only=True)
    # Public API shape is unchanged by the place CharField -> Place FK
    # migration: this still serializes to the place name, not its id.
    place = serializers.StringRelatedField()
    descriptions = HandDescriptionSerializer(many=True, read_only=True)

    class Meta:
        model = Hand
        fields = [
            "id",
            "name",
            "scribe",
            "item_part",
            "num",
            "priority",
            "is_default",
            "date",
            "place",
            "descriptions",
            "scriptorium",
        ]


class ScriptManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Script
        fields = ["id", "name"]


class ScribeManagementSerializer(serializers.ModelSerializer):
    period_display = serializers.StringRelatedField(source="period", read_only=True)
    hand_count = serializers.IntegerField(source="hand_set.count", read_only=True)

    class Meta:
        model = Scribe
        fields = ["id", "name", "period", "period_display", "scriptorium", "hand_count"]


class HandDescriptionManagementSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source="source.label", read_only=True, default=None)

    class Meta:
        model = HandDescription
        fields = ["id", "hand", "source", "source_label", "content"]


class HandManagementSerializer(serializers.ModelSerializer):
    scribe_name = serializers.CharField(source="scribe.name", read_only=True)
    item_part_display = serializers.StringRelatedField(source="item_part", read_only=True)
    script_name = serializers.CharField(source="script.name", read_only=True, default=None)
    date_display = serializers.StringRelatedField(source="date", read_only=True)
    place_display = serializers.StringRelatedField(source="place", read_only=True)
    descriptions = HandDescriptionManagementSerializer(many=True, read_only=True)

    class Meta:
        model = Hand
        fields = [
            "id",
            "name",
            "scribe",
            "scribe_name",
            "item_part",
            "item_part_display",
            "script",
            "script_name",
            "num",
            "priority",
            "is_default",
            "date",
            "date_display",
            "place",
            "place_display",
            "descriptions",
            "item_part_images",
        ]

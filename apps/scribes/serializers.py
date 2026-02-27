from rest_framework import serializers

from apps.symbols_structure.models import Allograph

from .models import Hand, Scribe, Script


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
        allographs = Allograph.objects.filter(graph__hand__scribe=instance).distinct().select_related("character")
        return IdiographSerializer(allographs, many=True).data


class HandSerializer(serializers.ModelSerializer):
    scriptorium = serializers.CharField(source="scribe.scriptorium", read_only=True)

    class Meta:
        model = Hand
        fields = ["id", "name", "scribe", "item_part", "date", "place", "description", "scriptorium"]


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


class HandManagementSerializer(serializers.ModelSerializer):
    scribe_name = serializers.CharField(source="scribe.name", read_only=True)
    item_part_display = serializers.StringRelatedField(source="item_part", read_only=True)
    script_name = serializers.CharField(source="script.name", read_only=True, default=None)
    date_display = serializers.StringRelatedField(source="date", read_only=True)

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
            "date",
            "date_display",
            "place",
            "description",
            "item_part_images",
        ]

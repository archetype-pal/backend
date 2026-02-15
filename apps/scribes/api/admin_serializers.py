from rest_framework import serializers

from apps.scribes.models import Hand, Scribe, Script


class ScriptAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Script
        fields = ["id", "name"]


class ScribeAdminSerializer(serializers.ModelSerializer):
    period_display = serializers.StringRelatedField(source="period", read_only=True)
    hand_count = serializers.IntegerField(source="hand_set.count", read_only=True)

    class Meta:
        model = Scribe
        fields = ["id", "name", "period", "period_display", "scriptorium", "hand_count"]


class HandAdminSerializer(serializers.ModelSerializer):
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

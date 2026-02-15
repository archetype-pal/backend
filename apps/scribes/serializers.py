from rest_framework import serializers

from apps.symbols_structure.models import Allograph

from .models import Hand, Scribe


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
        allographs = (
            Allograph.objects.filter(graph__hand__scribe=instance)
            .distinct()
            .select_related("character")
        )
        return IdiographSerializer(allographs, many=True).data


class HandSerializer(serializers.ModelSerializer):
    scriptorium = serializers.CharField(source="scribe.scriptorium", read_only=True)

    class Meta:
        model = Hand
        fields = ["id", "name", "scribe", "item_part", "date", "place", "description", "scriptorium"]

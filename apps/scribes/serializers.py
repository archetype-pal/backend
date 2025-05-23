from rest_framework import serializers

from .models import Hand, Scribe


class ScribeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scribe
        fields = ["id", "name", "period", "scriptorium"]


class HandSerializer(serializers.ModelSerializer):
    scriptorium = serializers.StringRelatedField()

    class Meta:
        model = Hand
        fields = ["id", "name", "scribe", "item_part", "date", "place", "description", "scriptorium"]

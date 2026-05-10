from rest_framework import serializers

from apps.common.models import Date, EditEvent


class DateManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "min_weight", "max_weight"]


class EditEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True)

    class Meta:
        model = EditEvent
        fields = [
            "id",
            "actor",
            "actor_username",
            "action",
            "target_type",
            "target_id",
            "summary",
            "payload",
            "created",
        ]
        read_only_fields = fields

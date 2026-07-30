from rest_framework import serializers

from apps.common.models import Date, SiteLabel


class DateManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "min_weight", "max_weight"]


class SiteLabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteLabel
        fields = ["id", "key", "value", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

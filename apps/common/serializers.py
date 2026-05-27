from rest_framework import serializers

from apps.common.models import Date


class DateManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "probable_text", "dating_notes", "min_weight", "max_weight"]

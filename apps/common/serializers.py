from rest_framework import serializers

from apps.common.models import Date, SiteLabels


class DateManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "min_weight", "max_weight"]


class SiteLabelsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteLabels
        fields = ["labels", "updated"]
        read_only_fields = ["updated"]

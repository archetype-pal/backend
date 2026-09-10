from rest_framework import serializers

from apps.common.models import Date, Place


class DateManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "min_weight", "max_weight"]


class PlaceManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = ["id", "name"]

from rest_framework import serializers

from apps.common.models import Date


class DateAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Date
        fields = ["id", "date", "min_weight", "max_weight"]

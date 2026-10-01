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

    def validate_name(self, value: str) -> str:
        # DRF only derives validators from field-based unique constraints, so the
        # case-insensitive one on Place would otherwise surface as a 500.
        name = value.strip()
        duplicates = Place.objects.filter(name__iexact=name)
        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError("A place with this name already exists.")
        return name

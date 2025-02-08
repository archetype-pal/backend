from rest_framework import serializers

from apps.symbols_structure.models import Allograph, AllographComponent, AllographComponentFeature, Position


class AllographFeatureSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="feature.id")
    name = serializers.CharField(source="feature.name")

    class Meta:
        model = AllographComponentFeature
        fields = ["id", "name", "set_by_default"]


class AllographComponentSerializer(serializers.ModelSerializer):
    features = AllographFeatureSerializer(many=True, source="allographcomponentfeature_set")

    class Meta:
        model = AllographComponent
        fields = ["component", "features"]


class AllographSerializer(serializers.ModelSerializer):
    components = AllographComponentSerializer(many=True, source="allographcomponent_set")

    class Meta:
        model = Allograph
        fields = ["id", "name", "components"]


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name"]

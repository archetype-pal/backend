from rest_framework import serializers

from apps.symbols_structure.models import (
    Allograph,
    AllographComponent,
    AllographComponentFeature,
    Character,
    Component,
    Feature,
    Position,
)
from apps.symbols_structure.services import CharacterStructureService


class AllographFeatureSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    set_by_default = serializers.BooleanField()


class AllographComponentSerializer(serializers.ModelSerializer):
    component_id = serializers.IntegerField(source="component.id")
    component_name = serializers.CharField(source="component.name")
    features = serializers.SerializerMethodField()

    class Meta:
        model = AllographComponent
        fields = ["component_id", "component_name", "features"]

    def get_features(self, obj):
        explicit_rows = list(obj.allographcomponentfeature_set.select_related("feature").all())

        if explicit_rows:
            return [
                {
                    "id": row.feature.id,
                    "name": row.feature.name,
                    "set_by_default": row.set_by_default,
                }
                for row in explicit_rows
            ]

        return [
            {
                "id": feature.id,
                "name": feature.name,
                "set_by_default": False,
            }
            for feature in obj.component.features.all()
        ]


class AllographPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name"]


class AllographSerializer(serializers.ModelSerializer):
    character_name = serializers.CharField(source="character.name", read_only=True)
    components = AllographComponentSerializer(many=True, source="allographcomponent_set")
    positions = AllographPositionSerializer(many=True, read_only=True)

    class Meta:
        model = Allograph
        fields = ["id", "name", "character_name", "components", "positions"]


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name"]


class FeatureManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ["id", "name"]


class ComponentManagementSerializer(serializers.ModelSerializer):
    features = serializers.PrimaryKeyRelatedField(many=True, queryset=Feature.objects.all(), required=False)

    class Meta:
        model = Component
        fields = ["id", "name", "features"]


class PositionManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name"]


class AllographManagementSerializer(serializers.ModelSerializer):
    character_name = serializers.CharField(source="character.name", read_only=True)

    class Meta:
        model = Allograph
        fields = ["id", "name", "character", "character_name"]


class AllographComponentManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllographComponent
        fields = ["id", "allograph", "component"]


class AllographComponentFeatureManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllographComponentFeature
        fields = ["id", "allograph_component", "feature", "set_by_default"]


class CharacterManagementSerializer(serializers.ModelSerializer):
    allograph_count = serializers.IntegerField(source="allograph_set.count", read_only=True)

    class Meta:
        model = Character
        fields = ["id", "name", "type", "allograph_count"]


class AllographComponentFeatureNestedSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Feature ID")
    set_by_default = serializers.BooleanField(default=False)


class AllographComponentNestedSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, help_text="AllographComponent ID (omit for new)")
    component_id = serializers.IntegerField()
    features = AllographComponentFeatureNestedSerializer(many=True, required=False)


class AllographNestedSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, help_text="Allograph ID (omit for new)")
    name = serializers.CharField(max_length=100)
    components = AllographComponentNestedSerializer(many=True, required=False)


class CharacterDetailManagementSerializer(serializers.ModelSerializer):
    allographs = serializers.SerializerMethodField()

    class Meta:
        model = Character
        fields = ["id", "name", "type", "allographs"]

    def get_allographs(self, character):
        allographs = character.allograph_set.prefetch_related(
            "allographcomponent_set__component__features",
            "allographcomponent_set__allographcomponentfeature_set__feature",
        ).all()
        result = []
        for allograph in allographs:
            allograph_data = {"id": allograph.id, "name": allograph.name, "components": []}
            for allograph_component in allograph.allographcomponent_set.all():
                explicit_feature_rows = {
                    row.feature_id: row for row in allograph_component.allographcomponentfeature_set.all()
                }

                component_data = {
                    "id": allograph_component.id,
                    "component_id": allograph_component.component_id,
                    "component_name": allograph_component.component.name,
                    "features": [],
                }

                for feature in allograph_component.component.features.all():
                    component_data["features"].append(
                        {
                            "id": feature.id,
                            "name": feature.name,
                            "set_by_default": explicit_feature_rows.get(feature.id).set_by_default
                            if feature.id in explicit_feature_rows
                            else False,
                        }
                    )

                allograph_data["components"].append(component_data)
            result.append(allograph_data)
        return result


class CharacterUpdateStructureSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    type = serializers.CharField(max_length=16, required=False, allow_null=True, allow_blank=True)
    allographs = AllographNestedSerializer(many=True)

    def update_structure(self, character, validated_data):
        service = CharacterStructureService()
        return service.update_structure(character=character, validated_data=validated_data)

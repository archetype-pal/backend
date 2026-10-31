from typing import Any

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


def _feature_row(feature: Feature, *, set_by_default: bool) -> dict[str, Any]:
    """A feature as the allograph structure lists it."""
    return {"id": feature.id, "name": feature.name, "set_by_default": set_by_default}


class AllographComponentSerializer(serializers.ModelSerializer):
    component_id = serializers.IntegerField(source="component.id")
    component_name = serializers.CharField(source="component.name")
    features = serializers.SerializerMethodField()

    class Meta:
        model = AllographComponent
        fields = ["component_id", "component_name", "features"]

    def get_features(self, obj):
        # `.all()` reads the view's prefetch; a select_related here would clone the
        # queryset and run one query per component instead.
        explicit_rows = list(obj.allographcomponentfeature_set.all())

        if explicit_rows:
            return [_feature_row(row.feature, set_by_default=row.set_by_default) for row in explicit_rows]

        return [_feature_row(feature, set_by_default=False) for feature in obj.component.features.all()]


class PositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name"]


class AllographSummarySerializer(serializers.ModelSerializer):
    """Lightweight allograph (id + labels only) for list/grouping/filter views.

    Skips the nested components/features/positions of `AllographSerializer` so
    consumers that only need labels (e.g. the annotation gallery's grouping)
    don't pull the whole taxonomy graph.
    """

    character_name = serializers.CharField(source="character.name", read_only=True)

    class Meta:
        model = Allograph
        fields = ["id", "name", "character_name"]


class AllographSerializer(AllographSummarySerializer):
    """An allograph with its components (and their features) and positions."""

    components = AllographComponentSerializer(many=True, source="allographcomponent_set")
    positions = PositionSerializer(many=True, read_only=True)

    class Meta(AllographSummarySerializer.Meta):
        fields = [*AllographSummarySerializer.Meta.fields, "components", "positions"]


class FeatureManagementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ["id", "name"]


class ComponentManagementSerializer(serializers.ModelSerializer):
    features = serializers.PrimaryKeyRelatedField(many=True, queryset=Feature.objects.all(), required=False)

    class Meta:
        model = Component
        fields = ["id", "name", "features"]


class AllographManagementSerializer(AllographSummarySerializer):
    class Meta(AllographSummarySerializer.Meta):
        fields = [*AllographSummarySerializer.Meta.fields, "character"]


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
            "allographcomponent_set__component",
            "allographcomponent_set__allographcomponentfeature_set__feature",
        ).all()
        result = []
        for allograph in allographs:
            allograph_data = {"id": allograph.id, "name": allograph.name, "components": []}
            for allograph_component in allograph.allographcomponent_set.all():
                component_data = {
                    "id": allograph_component.id,
                    "component_id": allograph_component.component_id,
                    "component_name": allograph_component.component.name,
                    "features": [],
                }

                for feature_set in allograph_component.allographcomponentfeature_set.all():
                    component_data["features"].append(
                        _feature_row(feature_set.feature, set_by_default=feature_set.set_by_default)
                    )

                allograph_data["components"].append(component_data)
            result.append(allograph_data)
        return result


class CharacterUpdateStructureSerializer(serializers.Serializer):
    """Input of `update-structure`; applied by `services.CharacterStructureService`."""

    name = serializers.CharField(max_length=100, required=False)
    type = serializers.CharField(max_length=16, required=False, allow_null=True, allow_blank=True)
    allographs = AllographNestedSerializer(many=True)

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

# ── Flat CRUD serializers ──────────────────────────────────────────────


class FeatureAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ["id", "name"]


class ComponentAdminSerializer(serializers.ModelSerializer):
    features = serializers.PrimaryKeyRelatedField(many=True, queryset=Feature.objects.all(), required=False)

    class Meta:
        model = Component
        fields = ["id", "name", "features"]


class PositionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Position
        fields = ["id", "name"]


class AllographAdminSerializer(serializers.ModelSerializer):
    character_name = serializers.CharField(source="character.name", read_only=True)

    class Meta:
        model = Allograph
        fields = ["id", "name", "character", "character_name"]


class AllographComponentAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllographComponent
        fields = ["id", "allograph", "component"]


class AllographComponentFeatureAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllographComponentFeature
        fields = ["id", "allograph_component", "feature", "set_by_default"]


class CharacterAdminSerializer(serializers.ModelSerializer):
    allograph_count = serializers.IntegerField(source="allograph_set.count", read_only=True)

    class Meta:
        model = Character
        fields = ["id", "name", "type", "allograph_count"]


# ── Nested serializers for the Character Detail / tree editor ──────────


class AllographComponentFeatureNestedSerializer(serializers.Serializer):
    """Represents a single feature within an AllographComponent, with set_by_default."""

    id = serializers.IntegerField(help_text="Feature ID")
    set_by_default = serializers.BooleanField(default=False)


class AllographComponentNestedSerializer(serializers.Serializer):
    """Represents a component attached to an allograph with its features."""

    id = serializers.IntegerField(
        required=False,
        help_text="AllographComponent ID (omit for new)",
    )
    component_id = serializers.IntegerField()
    features = AllographComponentFeatureNestedSerializer(many=True, required=False)


class AllographNestedSerializer(serializers.Serializer):
    """Represents an allograph with its components for nested write."""

    id = serializers.IntegerField(required=False, help_text="Allograph ID (omit for new)")
    name = serializers.CharField(max_length=100)
    components = AllographComponentNestedSerializer(many=True, required=False)


class CharacterDetailAdminSerializer(serializers.ModelSerializer):
    """
    Read: returns character with deeply nested allographs → components → features.
    Write: accepts the same structure and reconciles via custom update().
    """

    allographs = serializers.SerializerMethodField()

    class Meta:
        model = Character
        fields = ["id", "name", "type", "allographs"]

    # ── Read (GET) ──────────────────────────────────────────────────────

    def get_allographs(self, character):
        allographs = character.allograph_set.prefetch_related(
            "allographcomponent_set__component",
            "allographcomponent_set__allographcomponentfeature_set__feature",
        ).all()
        result = []
        for allo in allographs:
            allo_data = {"id": allo.id, "name": allo.name, "components": []}
            for ac in allo.allographcomponent_set.all():
                ac_data = {
                    "id": ac.id,
                    "component_id": ac.component_id,
                    "component_name": ac.component.name,
                    "features": [],
                }
                for acf in ac.allographcomponentfeature_set.all():
                    ac_data["features"].append(
                        {
                            "id": acf.feature_id,
                            "name": acf.feature.name,
                            "set_by_default": acf.set_by_default,
                        }
                    )
                allo_data["components"].append(ac_data)
            result.append(allo_data)
        return result


class CharacterUpdateStructureSerializer(serializers.Serializer):
    """
    Accepts the full nested tree for a character and reconciles
    creates/updates/deletes in a single transaction.
    """

    name = serializers.CharField(max_length=100, required=False)
    type = serializers.CharField(max_length=16, required=False, allow_null=True, allow_blank=True)
    allographs = AllographNestedSerializer(many=True)

    def update_structure(self, character, validated_data):
        from django.db import transaction

        with transaction.atomic():
            # Update character fields if provided
            if "name" in validated_data:
                character.name = validated_data["name"]
            if "type" in validated_data:
                character.type = validated_data["type"] or None
            character.save()

            allographs_data = validated_data.get("allographs", [])
            incoming_allo_ids = {a["id"] for a in allographs_data if "id" in a}

            # Delete allographs that are no longer in the payload
            character.allograph_set.exclude(id__in=incoming_allo_ids).delete()

            for allo_data in allographs_data:
                components_data = allo_data.pop("components", [])
                allo_id = allo_data.pop("id", None)

                if allo_id:
                    allograph = Allograph.objects.get(id=allo_id, character=character)
                    allograph.name = allo_data["name"]
                    allograph.save()
                else:
                    allograph = Allograph.objects.create(character=character, name=allo_data["name"])

                incoming_ac_ids = {c["id"] for c in components_data if "id" in c}
                allograph.allographcomponent_set.exclude(id__in=incoming_ac_ids).delete()

                for comp_data in components_data:
                    features_data = comp_data.pop("features", [])
                    ac_id = comp_data.pop("id", None)
                    component_id = comp_data["component_id"]

                    if ac_id:
                        ac = AllographComponent.objects.get(id=ac_id, allograph=allograph)
                        if ac.component_id != component_id:
                            ac.component_id = component_id
                            ac.save()
                    else:
                        ac = AllographComponent.objects.create(allograph=allograph, component_id=component_id)

                    # Reconcile features
                    incoming_feature_ids = {f["id"] for f in features_data}
                    ac.allographcomponentfeature_set.exclude(feature_id__in=incoming_feature_ids).delete()

                    for feat_data in features_data:
                        acf, _created = AllographComponentFeature.objects.update_or_create(
                            allograph_component=ac,
                            feature_id=feat_data["id"],
                            defaults={"set_by_default": feat_data.get("set_by_default", False)},
                        )

        character.refresh_from_db()
        return character

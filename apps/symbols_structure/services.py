"""Application services for symbols structure mutations."""

from django.db import transaction

from apps.symbols_structure.models import Allograph, AllographComponent, AllographComponentFeature


class CharacterStructureService:
    """Update character and nested allograph structure atomically."""

    def update_structure(self, character, validated_data):
        with transaction.atomic():
            if "name" in validated_data:
                character.name = validated_data["name"]
            if "type" in validated_data:
                character.type = validated_data["type"] or None
            character.save()

            allographs_data = validated_data.get("allographs", [])
            incoming_allograph_ids = {allograph["id"] for allograph in allographs_data if "id" in allograph}
            character.allograph_set.exclude(id__in=incoming_allograph_ids).delete()

            for allograph_data in allographs_data:
                components_data = allograph_data.pop("components", [])
                allograph_id = allograph_data.pop("id", None)

                if allograph_id:
                    allograph = Allograph.objects.get(id=allograph_id, character=character)
                    allograph.name = allograph_data["name"]
                    allograph.save()
                else:
                    allograph = Allograph.objects.create(character=character, name=allograph_data["name"])

                incoming_component_ids = {component["id"] for component in components_data if "id" in component}
                allograph.allographcomponent_set.exclude(id__in=incoming_component_ids).delete()

                for component_data in components_data:
                    features_data = component_data.pop("features", [])
                    allograph_component_id = component_data.pop("id", None)
                    component_id = component_data["component_id"]

                    if allograph_component_id:
                        allograph_component = AllographComponent.objects.get(
                            id=allograph_component_id,
                            allograph=allograph,
                        )
                        if allograph_component.component_id != component_id:
                            allograph_component.component_id = component_id
                            allograph_component.save()
                    else:
                        allograph_component = AllographComponent.objects.create(
                            allograph=allograph,
                            component_id=component_id,
                        )

                    incoming_feature_ids = {feature["id"] for feature in features_data}
                    allograph_component.allographcomponentfeature_set.exclude(
                        feature_id__in=incoming_feature_ids
                    ).delete()

                    for feature_data in features_data:
                        AllographComponentFeature.objects.update_or_create(
                            allograph_component=allograph_component,
                            feature_id=feature_data["id"],
                            defaults={"set_by_default": feature_data.get("set_by_default", False)},
                        )

        character.refresh_from_db()
        return character

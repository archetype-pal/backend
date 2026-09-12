from rest_framework import status
from rest_framework.test import APITestCase

from apps.symbols_structure.models import AllographComponent, AllographComponentFeature
from apps.symbols_structure.tests.factories import (
    AllographComponentFactory,
    AllographComponentFeatureFactory,
    AllographFactory,
    AllographPositionFactory,
    CharacterFactory,
    ComponentFactory,
    FeatureFactory,
    PositionFactory,
)
from apps.users.tests.factories import UserFactory


class TestAllographAPI(APITestCase):
    def setUp(self):
        self.allographs = AllographFactory.create_batch(10)
        components = ComponentFactory.create_batch(5)
        self.features = FeatureFactory.create_batch(10)
        for component in components:
            allograph_component = AllographComponent.objects.create(
                allograph=self.allographs[0],
                component=component,
            )
            for feature in self.features[6:9]:
                AllographComponentFeature.objects.create(
                    allograph_component=allograph_component, feature=feature, set_by_default=True
                )
        self.positions = PositionFactory.create_batch(4)
        for position in self.positions[:2]:
            AllographPositionFactory(allograph=self.allographs[0], position=position)

    def test_list_allographs(self):
        response = self.client.get("/api/v1/symbols_structure/allographs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)
        # Find the allograph that has components (ordering is by name, not PK)
        allograph_with_components = next(a for a in response.data if len(a["components"]) > 0)
        self.assertEqual(len(allograph_with_components["components"]), 5)
        self.assertEqual(len(allograph_with_components["components"][0]["features"]), 3)
        assert allograph_with_components["components"][0]["features"][0]["id"] == self.features[6].id
        assert allograph_with_components["components"][0]["features"][2]["id"] == self.features[8].id
        self.assertEqual(len(allograph_with_components["positions"]), 2)
        assert "id" in allograph_with_components["positions"][0]
        assert "name" in allograph_with_components["positions"][0]
        self.assertEqual(
            allograph_with_components["character_name"],
            self.allographs[0].character.name,
        )

    def test_list_allographs_light_omits_nested_schema(self):
        # `?light=1` returns labels only (id, name, character_name) without the
        # nested components/positions graph — used by the annotation gallery's
        # grouping/filter so a page load doesn't pull the whole taxonomy (G2.3).
        response = self.client.get("/api/v1/symbols_structure/allographs/?light=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)
        sample = response.data[0]
        self.assertEqual(set(sample.keys()), {"id", "name", "character_name"})

    def test_list_allographs_falls_back_to_component_features_without_explicit_rows(self):
        allograph = AllographFactory()
        component = ComponentFactory()
        feature = FeatureFactory()
        component.features.add(feature)
        AllographComponentFactory(allograph=allograph, component=component)

        response = self.client.get("/api/v1/symbols_structure/allographs/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        allograph_payload = next(item for item in response.data if item["id"] == allograph.id)
        self.assertEqual(
            allograph_payload["components"][0]["features"],
            [{"id": feature.id, "name": feature.name, "set_by_default": False}],
        )


class TestPositionAPI(APITestCase):
    def setUp(self):
        self.positions = PositionFactory.create_batch(4)

    def test_list_positions(self):
        response = self.client.get("/api/v1/symbols_structure/positions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)


class TestCharacterManagementAPI(APITestCase):
    def setUp(self):
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(user=self.superuser)

    @staticmethod
    def _component_payload(response_data, allograph_component_id):
        return next(
            component
            for allograph in response_data["allographs"]
            for component in allograph["components"]
            if component["id"] == allograph_component_id
        )

    def test_retrieve_character_returns_explicit_allograph_component_features(self):
        character = CharacterFactory(name="a")
        allograph = AllographFactory(character=character, name="without head")
        component = ComponentFactory(name="Stem")
        template_only_feature = FeatureFactory(name="template only")
        selected_template_feature = FeatureFactory(name="selected template")
        selected_specific_feature = FeatureFactory(name="selected specific")
        component.features.add(template_only_feature, selected_template_feature)
        allograph_component = AllographComponentFactory(allograph=allograph, component=component)
        AllographComponentFeatureFactory(
            allograph_component=allograph_component,
            feature=selected_template_feature,
            set_by_default=False,
        )
        AllographComponentFeatureFactory(
            allograph_component=allograph_component,
            feature=selected_specific_feature,
            set_by_default=True,
        )

        response = self.client.get(f"/api/v1/symbols_structure/management/symbols/characters/{character.id}/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        component_payload = self._component_payload(response.data, allograph_component.id)
        self.assertCountEqual(
            [feature["id"] for feature in component_payload["features"]],
            [selected_template_feature.id, selected_specific_feature.id],
        )
        self.assertNotIn(
            template_only_feature.id,
            [feature["id"] for feature in component_payload["features"]],
        )
        self.assertEqual(
            next(feature for feature in component_payload["features"] if feature["id"] == selected_specific_feature.id)[
                "set_by_default"
            ],
            True,
        )

    def test_update_structure_response_keeps_unselected_template_features_unselected(self):
        character = CharacterFactory(name="b")
        allograph = AllographFactory(character=character, name="b")
        component = ComponentFactory(name="Bowl")
        retained_feature = FeatureFactory(name="retained")
        removed_feature = FeatureFactory(name="removed")
        component.features.add(retained_feature, removed_feature)
        allograph_component = AllographComponentFactory(allograph=allograph, component=component)
        AllographComponentFeatureFactory(
            allograph_component=allograph_component,
            feature=retained_feature,
        )
        AllographComponentFeatureFactory(
            allograph_component=allograph_component,
            feature=removed_feature,
        )

        response = self.client.post(
            f"/api/v1/symbols_structure/management/symbols/characters/{character.id}/update-structure/",
            {
                "name": character.name,
                "type": character.type,
                "allographs": [
                    {
                        "id": allograph.id,
                        "name": allograph.name,
                        "components": [
                            {
                                "id": allograph_component.id,
                                "component_id": component.id,
                                "features": [{"id": retained_feature.id, "set_by_default": False}],
                            }
                        ],
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            list(allograph_component.allographcomponentfeature_set.values_list("feature_id", flat=True)),
            [retained_feature.id],
        )
        component_payload = self._component_payload(response.data, allograph_component.id)
        self.assertEqual(
            [feature["id"] for feature in component_payload["features"]],
            [retained_feature.id],
        )

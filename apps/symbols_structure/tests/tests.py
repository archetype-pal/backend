from rest_framework import status
from rest_framework.test import APITestCase

from apps.symbols_structure.models import AllographComponent, AllographComponentFeature
from apps.symbols_structure.tests.factories import (
    AllographFactory,
    AllographPositionFactory,
    ComponentFactory,
    FeatureFactory,
    PositionFactory,
)


class TestAllographAPI(APITestCase):
    def setUp(self):
        allographs = AllographFactory.create_batch(10)
        components = ComponentFactory.create_batch(5)
        self.features = FeatureFactory.create_batch(10)
        for component in components:
            allograph_component = AllographComponent.objects.create(allograph=allographs[0], component=component)
            for feature in self.features[6:9]:
                AllographComponentFeature.objects.create(
                    allograph_component=allograph_component, feature=feature, set_by_default=True
                )
        self.positions = PositionFactory.create_batch(4)
        for position in self.positions[:2]:
            AllographPositionFactory(allograph=allographs[0], position=position)

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


class TestPositionAPI(APITestCase):
    def setUp(self):
        self.positions = PositionFactory.create_batch(4)

    def test_list_positions(self):
        response = self.client.get("/api/v1/symbols_structure/positions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)

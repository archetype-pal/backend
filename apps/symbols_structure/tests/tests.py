from rest_framework import status
from rest_framework.test import APITestCase

from apps.symbols_structure.models import AllographComponent, AllographComponentFeature
from apps.symbols_structure.tests.factories import AllographFactory, ComponentFactory, FeatureFactory, PositionFactory


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

    def test_list_allographs(self):
        response = self.client.get("/api/v1/symbols_structure/allographs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 10)
        self.assertEqual(len(response.data[0]["components"]), 5)
        self.assertEqual(len(response.data[0]["components"][0]["features"]), 3)
        assert response.data[0]["components"][0]["features"][0]["id"] == self.features[6].id
        assert response.data[0]["components"][0]["features"][2]["id"] == self.features[8].id


class TestPositionAPI(APITestCase):
    def setUp(self):
        self.positions = PositionFactory.create_batch(4)

    def test_list_positions(self):
        response = self.client.get("/api/v1/symbols_structure/positions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 4)

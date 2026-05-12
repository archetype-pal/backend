"""API tests for scribes and hands public endpoints."""

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.scribes.tests.factories import HandFactory, ScribeFactory


class ScribeAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.scribe = ScribeFactory()

    def test_scribe_list_returns_200(self):
        response = self.client.get("/api/v1/scribes/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_scribe_retrieve_returns_200(self):
        response = self.client.get(f"/api/v1/scribes/{self.scribe.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.scribe.id)
        self.assertEqual(response.data["name"], self.scribe.name)


class HandAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.hand = HandFactory()

    def test_hand_list_returns_200(self):
        response = self.client.get("/api/v1/hands/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_hand_retrieve_returns_200(self):
        response = self.client.get(f"/api/v1/hands/{self.hand.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.hand.id)
        self.assertEqual(response.data["name"], self.hand.name)
        self.assertEqual(response.data["num"], self.hand.num)
        self.assertEqual(response.data["priority"], self.hand.priority)
        self.assertEqual(response.data["is_default"], self.hand.is_default)

    def test_hand_list_orders_by_default_priority_and_num(self):
        item_part = self.hand.item_part
        low_order = HandFactory(item_part=item_part, name="B", num=2, priority=0)
        high_order = HandFactory(item_part=item_part, name="A", num=1, priority=0)
        preferred = HandFactory(item_part=item_part, name="C", num=99, priority=10)
        default = HandFactory(item_part=item_part, name="D", num=100, priority=0, is_default=True)

        response = self.client.get(f"/api/v1/hands/?item_part={item_part.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result_ids = [row["id"] for row in response.data["results"]]

        self.assertLess(result_ids.index(default.id), result_ids.index(preferred.id))
        self.assertLess(result_ids.index(preferred.id), result_ids.index(high_order.id))
        self.assertLess(result_ids.index(high_order.id), result_ids.index(low_order.id))

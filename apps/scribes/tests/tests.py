"""API tests for scribes and hands public endpoints."""

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.manuscripts.tests.factories import ItemPartFactory
from apps.scribes.models import Hand
from apps.scribes.tests.factories import HandFactory, ScribeFactory
from apps.users.tests.factories import UserFactory


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


class HandManagementAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = UserFactory(is_superuser=True, is_staff=True)
        self.client.force_authenticate(self.superuser)
        self.scribe = ScribeFactory()
        self.item_part = ItemPartFactory()

    def test_create_hand_allows_omitted_description(self):
        response = self.client.post(
            "/api/v1/management/scribes/hands/",
            {
                "name": "Hand without description",
                "scribe": self.scribe.id,
                "item_part": self.item_part.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        hand = Hand.objects.get(id=response.data["id"])
        self.assertEqual(hand.description, "")
        self.assertEqual(response.data["description"], "")

    def test_update_hand_allows_blank_description(self):
        hand = HandFactory(description="Existing description")

        response = self.client.patch(
            f"/api/v1/management/scribes/hands/{hand.id}/",
            {"description": ""},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        hand.refresh_from_db()
        self.assertEqual(hand.description, "")

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

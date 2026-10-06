"""API tests for common views (schema, docs)."""

import pytest
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.manuscripts.models import Repository
from apps.manuscripts.tests.factories import RepositoryFactory


class SchemaAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_schema_returns_200_and_openapi_shape(self):
        response = self.client.get("/api/v1/schema/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("paths", response.data)
        self.assertIsInstance(response.data["paths"], dict)


@pytest.mark.django_db
def test_a_list_page_holds_at_most_100_rows(management_client):
    Repository.objects.bulk_create(RepositoryFactory.build_batch(101))

    response = management_client.get("/api/v1/manuscripts/management/repositories/", {"limit": 500})

    assert response.status_code == 200
    assert response.data["count"] == 101
    assert len(response.data["results"]) == 100

"""API tests for common views (schema, docs)."""

from rest_framework import status
from rest_framework.test import APIClient, APITestCase


class SchemaAPITestCase(APITestCase):
    def setUp(self):
        self.client = APIClient()

    def test_schema_returns_200_and_openapi_shape(self):
        response = self.client.get("/api/v1/schema/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("paths", response.data)
        self.assertIsInstance(response.data["paths"], dict)


class PaginationConfigurationTestCase(APITestCase):
    def test_bounded_limit_offset_pagination_defaults_and_max(self):
        from config.pagination import BoundedLimitOffsetPagination

        pagination = BoundedLimitOffsetPagination()
        self.assertEqual(pagination.default_limit, 20)
        self.assertEqual(pagination.max_limit, 100)

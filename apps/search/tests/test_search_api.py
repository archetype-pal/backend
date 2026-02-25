"""API-layer tests for the search API. Require Meilisearch (e.g. via Docker Compose)."""

from django.core.management import call_command
from meilisearch.errors import MeilisearchCommunicationError
import pytest
from rest_framework import status

from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.types import IndexType


@pytest.fixture
def meilisearch_indexes(db):
    """Ensure Meilisearch indexes exist and item-parts has one document for retrieve tests."""
    try:
        call_command("setup_search_indexes")
        writer = MeilisearchIndexWriter()
        # Add one document so retrieve can return 200
        writer.replace_documents(
            IndexType.ITEM_PARTS,
            [{"id": 1, "shelfmark": "Test MS", "repository_name": "Test Repo", "repository_city": "City"}],
        )
    except MeilisearchCommunicationError:
        pytest.skip("Meilisearch is not available for search API integration tests.")


@pytest.mark.django_db
class TestSearchListAPI:
    """GET /api/v1/search/{index_type}/"""

    def test_list_invalid_index_type_returns_404(self, api_client):
        response = api_client.get("/api/v1/search/invalid-type/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "detail" in response.data

    def test_list_valid_index_type_returns_200_and_shape(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/")
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert "total" in response.data
        assert "limit" in response.data
        assert "offset" in response.data
        assert isinstance(response.data["results"], list)
        assert isinstance(response.data["total"], int)
        assert isinstance(response.data["limit"], int)
        assert isinstance(response.data["offset"], int)

    def test_list_accepts_limit_offset_ordering(self, api_client, meilisearch_indexes):
        response = api_client.get(
            "/api/v1/search/item-parts/",
            {"limit": 5, "offset": 0, "ordering": "-shelfmark"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["limit"] == 5
        assert response.data["offset"] == 0

    def test_list_accepts_selected_facets(self, api_client, meilisearch_indexes):
        # API accepts selected_facets as "attr:value"; attr_exact is normalized to attr for Meilisearch
        response = api_client.get(
            "/api/v1/search/item-parts/",
            {"selected_facets": "type:charter"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_list_accepts_selected_facets_with_exact_suffix(self, api_client, meilisearch_indexes):
        # Frontend sends image_availability_exact; backend normalizes to image_availability for filter
        response = api_client.get(
            "/api/v1/search/item-parts/",
            {"selected_facets": "image_availability_exact:With images"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_list_all_index_types_return_200(self, api_client, meilisearch_indexes):
        for segment in ["item-parts", "item-images", "scribes", "hands", "graphs"]:
            response = api_client.get(f"/api/v1/search/{segment}/")
            assert response.status_code == status.HTTP_200_OK, f"Failed for {segment}"


@pytest.mark.django_db
class TestSearchFacetsAPI:
    """GET /api/v1/search/{index_type}/facets/"""

    def test_facets_invalid_index_type_returns_404(self, api_client):
        response = api_client.get("/api/v1/search/invalid-type/facets/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "detail" in response.data

    def test_facets_returns_200_and_shape(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/facets/")
        assert response.status_code == status.HTTP_200_OK
        assert "facetDistribution" in response.data
        assert "results" in response.data
        assert "total" in response.data
        assert "limit" in response.data
        assert "offset" in response.data
        assert "next" in response.data
        assert "previous" in response.data
        assert "ordering" in response.data
        assert isinstance(response.data["facetDistribution"], dict)
        assert isinstance(response.data["results"], list)
        assert isinstance(response.data["ordering"], dict)
        assert "current" in response.data["ordering"]
        assert "options" in response.data["ordering"]

    def test_facets_accepts_query_params(self, api_client, meilisearch_indexes):
        response = api_client.get(
            "/api/v1/search/item-parts/facets/",
            {"limit": 10, "offset": 0, "ordering": "id"},
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["limit"] == 10
        assert response.data["offset"] == 0


@pytest.mark.django_db
class TestSearchRetrieveAPI:
    """GET /api/v1/search/{index_type}/{id}/"""

    def test_retrieve_invalid_index_type_returns_404(self, api_client):
        response = api_client.get("/api/v1/search/invalid-type/1/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "detail" in response.data

    def test_retrieve_not_found_returns_404(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/99999/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "detail" in response.data

    def test_retrieve_returns_200_when_document_exists(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/1/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == 1
        assert "shelfmark" in response.data

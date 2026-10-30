"""Search API against a live Meilisearch (skipped without one): what the index settings accept.

The HTTP contract itself is covered offline in `test_views_offline.py`; these pin
that the filters, sorts and date windows the views compile are ones Meilisearch
takes, on every index.
"""

from django.core.management import call_command
from meilisearch.errors import MeilisearchCommunicationError
import pytest
from rest_framework import status

from apps.search.meilisearch.writer import MeilisearchIndexWriter
from apps.search.types import IndexType


@pytest.fixture(scope="session")
def _configured_search_indexes():
    """Create and configure the indexes once per session; it takes seconds and only touches Meilisearch."""
    try:
        call_command("setup_search_indexes")
    except MeilisearchCommunicationError:
        pytest.skip("Meilisearch is not available for search API integration tests.")


def _seed_documents(index_type: IndexType, documents: list[dict]) -> None:
    """Write documents straight into the live index and wait until they are searchable.

    Test-only: production writes go through the build-and-swap reindex or the
    fire-and-forget incremental sync, neither of which blocks on the task.
    """
    writer = MeilisearchIndexWriter()
    writer.ensure_index_and_settings(index_type)
    index = writer.client.index(writer._index_uid(index_type))
    task = index.update_documents(documents, primary_key=writer.PRIMARY_KEY)
    writer.client.wait_for_task(task.task_uid, timeout_in_ms=writer.TASK_TIMEOUT_MS)


@pytest.fixture
def meilisearch_indexes(db, _configured_search_indexes):
    """Ensure Meilisearch indexes exist and item-parts has one document for retrieve tests."""
    try:
        _seed_documents(
            IndexType.ITEM_PARTS,
            [{"id": 1, "shelfmark": "Test MS", "repository_name": "Test Repo", "repository_city": "City"}],
        )
    except MeilisearchCommunicationError:
        pytest.skip("Meilisearch is not available for search API integration tests.")


@pytest.mark.django_db
class TestSearchListAPI:
    """GET /api/v1/search/{index_type}/"""

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
        response = api_client.get(
            "/api/v1/search/item-parts/",
            {"selected_facets": "type:charter"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_list_accepts_selected_facets_with_exact_suffix(self, api_client, meilisearch_indexes):
        response = api_client.get(
            "/api/v1/search/item-parts/",
            {"selected_facets": "image_availability_exact:With images"},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_list_accepts_an_offset_past_the_last_hit(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/", {"offset": str(2**64)})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []

    def test_list_accepts_a_filter_value_ending_in_a_backslash(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/scribes/", {"name": "foo\\"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"] == []

    def test_list_all_index_types_return_200(self, api_client, meilisearch_indexes):
        for segment in ["item-parts", "item-images", "scribes", "hands", "graphs"]:
            response = api_client.get(f"/api/v1/search/{segment}/")
            assert response.status_code == status.HTTP_200_OK, f"Failed for {segment}"

    def test_list_date_range_is_accepted_on_every_index_type(self, api_client, meilisearch_indexes):
        # Indexes without date fields ignore the range rather than erroring.
        for segment in ["item-parts", "item-images", "scribes", "hands", "graphs"]:
            response = api_client.get(f"/api/v1/search/{segment}/", {"min_date": 1100, "max_date": 1200})
            assert response.status_code == status.HTTP_200_OK, f"Failed for {segment}"


@pytest.mark.django_db
class TestSearchFacetsAPI:
    """GET /api/v1/search/{index_type}/facets/"""

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

    def test_retrieve_not_found_returns_404(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/99999/")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "detail" in response.data

    def test_retrieve_returns_200_when_document_exists(self, api_client, meilisearch_indexes):
        response = api_client.get("/api/v1/search/item-parts/1/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == 1
        assert "shelfmark" in response.data

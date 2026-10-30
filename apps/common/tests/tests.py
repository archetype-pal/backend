"""Cross-cutting API behaviour: the merged schema document and the page-size cap."""

import pytest

from apps.manuscripts.models import Repository
from apps.manuscripts.tests.factories import RepositoryFactory


def test_schema_is_served_as_one_openapi_document(api_client):
    response = api_client.get("/api/v1/schema/")

    assert response.status_code == 200
    assert "/api/v1/manuscripts/item-parts/" in response.data["paths"]


@pytest.mark.django_db
def test_a_list_page_holds_at_most_100_rows(management_client):
    Repository.objects.bulk_create(RepositoryFactory.build_batch(101))

    response = management_client.get("/api/v1/manuscripts/management/repositories/", {"limit": 500})

    assert response.status_code == 200
    assert response.data["count"] == 101
    assert len(response.data["results"]) == 100

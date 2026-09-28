import pytest

from apps.manuscripts.tests.factories import CurrentItemFactory, RepositoryFactory


@pytest.mark.django_db
def test_repository_list_reports_current_item_count(management_client):
    current_item = CurrentItemFactory()
    CurrentItemFactory(repository=current_item.repository)
    empty = RepositoryFactory()

    response = management_client.get("/api/v1/manuscripts/management/repositories/")

    counts = {row["id"]: row["current_item_count"] for row in response.data["results"]}
    assert counts == {current_item.repository_id: 2, empty.id: 0}

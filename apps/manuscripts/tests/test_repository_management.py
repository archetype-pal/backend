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


@pytest.mark.django_db
def test_repository_pages_follow_name_order_without_repeats(management_client):
    for name in ["Beta", "Alpha", "Alpha", "Gamma"]:
        CurrentItemFactory(repository=RepositoryFactory(name=name))

    rows = []
    for offset in range(4):
        page = management_client.get("/api/v1/manuscripts/management/repositories/", {"limit": 1, "offset": offset})
        rows += page.data["results"]

    assert [row["name"] for row in rows] == ["Alpha", "Alpha", "Beta", "Gamma"]
    assert len({row["id"] for row in rows}) == 4

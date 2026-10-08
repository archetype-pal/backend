import pytest

from apps.manuscripts.tests.factories import CurrentItemFactory, ItemPartFactory, RepositoryFactory

HISTORICAL_ITEMS_URL = "/api/v1/manuscripts/management/historical-items/"
CURRENT_ITEMS_URL = "/api/v1/manuscripts/management/current-items/"


@pytest.mark.django_db
def test_current_items_sort_by_part_count(management_client):
    busy, quiet = CurrentItemFactory(), CurrentItemFactory()
    ItemPartFactory.create_batch(2, current_item=busy)
    ItemPartFactory(current_item=quiet)

    rows = management_client.get(CURRENT_ITEMS_URL, {"ordering": "-part_count"}).data["results"]

    assert [(row["id"], row["part_count"]) for row in rows] == [(busy.id, 2), (quiet.id, 1)]


@pytest.mark.django_db
def test_historical_items_sort_by_the_first_part_shelfmark(management_client):
    repository = RepositoryFactory(label="Repo")
    later = ItemPartFactory(current_item=CurrentItemFactory(repository=repository, shelfmark="B 2")).historical_item
    earlier = ItemPartFactory(current_item=CurrentItemFactory(repository=repository, shelfmark="A 1")).historical_item
    ItemPartFactory(historical_item=later, current_item=CurrentItemFactory(repository=repository, shelfmark="A 0"))
    ordering = {"ordering": "first_repository_label,first_shelfmark"}

    rows = management_client.get(HISTORICAL_ITEMS_URL, ordering).data["results"]
    searched = management_client.get(HISTORICAL_ITEMS_URL, {**ordering, "search": "Repo"}).data["results"]

    assert [row["id"] for row in rows] == [earlier.id, later.id]
    assert [row["id"] for row in searched] == [earlier.id, later.id]

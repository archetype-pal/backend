import pytest

from apps.common.tests.factories import DateFactory
from apps.manuscripts.tests.factories import (
    CurrentItemFactory,
    HistoricalItemFactory,
    ItemPartFactory,
    RepositoryFactory,
)

HISTORICAL_ITEMS_URL = "/api/v1/manuscripts/management/historical-items/"
CURRENT_ITEMS_URL = "/api/v1/manuscripts/management/current-items/"


@pytest.mark.django_db
def test_current_items_sort_by_part_count(management_client):
    repository = RepositoryFactory()
    # Shelfmark order, the default, puts `quiet` first.
    busy = CurrentItemFactory(repository=repository, shelfmark="MS 2")
    quiet = CurrentItemFactory(repository=repository, shelfmark="MS 1")
    ItemPartFactory.create_batch(2, current_item=busy)
    ItemPartFactory(current_item=quiet)

    rows = management_client.get(CURRENT_ITEMS_URL, {"ordering": "-part_count"}).data["results"]

    assert [(row["id"], row["part_count"]) for row in rows] == [(busy.id, 2), (quiet.id, 1)]


@pytest.mark.django_db
def test_current_items_sort_by_the_repository_label_they_show(management_client):
    # Name order, the default, puts `zeta` first.
    zeta = CurrentItemFactory(repository=RepositoryFactory(name="Alpha", label="Zeta"))
    eta = CurrentItemFactory(repository=RepositoryFactory(name="Beta", label="Eta"))

    rows = management_client.get(CURRENT_ITEMS_URL, {"ordering": "repository__label"}).data["results"]

    assert [row["id"] for row in rows] == [eta.id, zeta.id]


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


@pytest.mark.django_db
@pytest.mark.parametrize(("ordering", "dated_order"), [("date__min_weight", [0, 1]), ("-date__min_weight", [1, 0])])
def test_historical_items_sort_by_date_weight_with_undated_last(management_client, ordering, dated_order):
    undated = HistoricalItemFactory(date=None)
    dated = [HistoricalItemFactory(date=DateFactory(min_weight=weight)) for weight in (1100, 1200)]
    undated_too = HistoricalItemFactory(date=None)

    rows = management_client.get(HISTORICAL_ITEMS_URL, {"ordering": ordering}).data["results"]

    assert [row["id"] for row in rows] == [dated[i].id for i in dated_order] + [undated.id, undated_too.id]

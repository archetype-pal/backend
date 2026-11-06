import pytest

from apps.common.tests.factories import PlaceFactory
from apps.common.tests.query_counts import assert_query_count_constant
from apps.manuscripts.tests.factories import CurrentItemFactory, RepositoryFactory

URL = "/api/v1/manuscripts/management/repositories/"


@pytest.mark.django_db
def test_repository_list_reports_current_item_count(management_client):
    current_item = CurrentItemFactory()
    CurrentItemFactory(repository=current_item.repository)
    empty = RepositoryFactory()

    response = management_client.get("/api/v1/manuscripts/management/repositories/")

    counts = {row["id"]: row["current_item_count"] for row in response.data["results"]}
    assert counts == {current_item.repository_id: 2, empty.id: 0}


@pytest.mark.django_db
def test_a_repository_reads_its_place_as_an_id_and_a_name(management_client):
    repository = RepositoryFactory(place=PlaceFactory(name="Winchester"))

    response = management_client.get(f"{URL}{repository.pk}/")

    assert response.data["place"] == repository.place_id
    assert response.data["place_display"] == "Winchester"


@pytest.mark.django_db
def test_a_repository_takes_its_place_from_the_place_list_and_can_drop_it(management_client):
    repository = RepositoryFactory(place=None)
    place = PlaceFactory()

    response = management_client.patch(f"{URL}{repository.pk}/", data={"place": place.pk}, format="json")

    assert response.status_code == 200
    repository.refresh_from_db()
    assert repository.place == place

    management_client.patch(f"{URL}{repository.pk}/", data={"place": None}, format="json")

    repository.refresh_from_db()
    assert repository.place is None


@pytest.mark.django_db
def test_the_repository_list_query_count_does_not_grow_with_rows(management_client):
    assert_query_count_constant(management_client, URL, RepositoryFactory.create_batch)

from django.core.exceptions import ValidationError
import pytest

from apps.common.tests.factories import PlaceFactory
from apps.common.tests.query_counts import assert_query_count_constant
from apps.manuscripts.tests.factories import HistoricalItemFactory, HistoricalItemOriginFactory, ItemPartFactory

URL = "/api/v1/manuscripts/management/origins/"

pytestmark = pytest.mark.django_db


def test_an_origin_is_added_and_shows_on_the_manuscript(management_client):
    item = HistoricalItemFactory()
    place = PlaceFactory(name="Worcester")

    response = management_client.post(
        URL,
        {"historical_item": item.pk, "place": place.pk, "evidence": "Ker 1957", "dubitable": True},
        format="json",
    )

    assert response.status_code == 201
    detail = management_client.get(f"/api/v1/manuscripts/management/historical-items/{item.pk}/")
    assert [
        (origin["place_display"], origin["evidence"], origin["dubitable"]) for origin in detail.data["origins"]
    ] == [("Worcester", "Ker 1957", True)]


def test_the_origin_list_filters_by_manuscript_and_stays_flat(management_client):
    origin = HistoricalItemOriginFactory()
    HistoricalItemOriginFactory()

    response = management_client.get(URL, {"historical_item": origin.historical_item_id})

    assert [row["id"] for row in response.data["results"]] == [origin.pk]
    assert_query_count_constant(management_client, URL, HistoricalItemOriginFactory.create_batch)


def test_an_origin_cannot_be_moved_to_another_manuscript(management_client):
    origin = HistoricalItemOriginFactory()
    original_item_id = origin.historical_item_id

    response = management_client.patch(
        f"{URL}{origin.pk}/", {"historical_item": HistoricalItemFactory().pk}, format="json"
    )

    assert response.status_code == 400, response.data
    assert "historical_item" in response.data
    origin.refresh_from_db()
    assert origin.historical_item_id == original_item_id


def test_an_origin_update_accepts_its_own_manuscript(management_client):
    origin = HistoricalItemOriginFactory()

    response = management_client.patch(
        f"{URL}{origin.pk}/", {"historical_item": origin.historical_item_id, "evidence": "Ker 1957"}, format="json"
    )

    assert response.status_code == 200, response.data
    origin.refresh_from_db()
    assert origin.evidence == "Ker 1957"


def test_a_place_that_is_an_origin_cannot_be_deleted(management_client):
    origin = HistoricalItemOriginFactory()

    response = management_client.delete(f"/api/v1/management/common/places/{origin.place_id}/")

    assert response.status_code == 409


def test_the_public_manuscript_names_its_origins(api_client):
    part = ItemPartFactory()
    HistoricalItemOriginFactory(historical_item=part.historical_item, place=PlaceFactory(name="Exeter"))
    HistoricalItemOriginFactory(
        historical_item=part.historical_item, place=PlaceFactory(name="Canterbury"), dubitable=True
    )

    response = api_client.get(f"/api/v1/manuscripts/item-parts/{part.pk}/")

    assert response.data["historical_item"]["origins"] == [
        {"place": "Exeter", "dubitable": False},
        {"place": "Canterbury", "dubitable": True},
    ]


@pytest.mark.django_db
def test_the_model_refuses_a_move_to_another_manuscript():
    origin = HistoricalItemOriginFactory()
    origin.historical_item = HistoricalItemFactory()

    with pytest.raises(ValidationError):
        origin.save()


@pytest.mark.django_db
def test_a_manuscript_cannot_have_the_same_origin_twice(management_client):
    origin = HistoricalItemOriginFactory()

    response = management_client.post(
        URL, {"historical_item": origin.historical_item_id, "place": origin.place_id}, format="json"
    )

    assert response.status_code == 400

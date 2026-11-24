from typing import cast

import pytest
from rest_framework.test import APIClient

from apps.common.tests.factories import DateFactory
from apps.manuscripts.models import HistoricalItem, ItemPart
from apps.manuscripts.tests.factories import ItemPartFactory

pytestmark = pytest.mark.django_db

ITEMS_URL = "/api/v1/manuscripts/management/historical-items/"
DATING = {"probable_text_date": "probably 1140s", "dating_notes": "Assigned from catalogue evidence."}


def _dating(response) -> dict:
    return {"probable_text_date": response.data["probable_text_date"], "dating_notes": response.data["dating_notes"]}


def _item_with_dating(management_client) -> HistoricalItem:
    item: HistoricalItem = cast(ItemPart, ItemPartFactory()).historical_item
    response = management_client.patch(f"{ITEMS_URL}{item.pk}/", DATING, format="json")
    assert response.status_code == 200
    return item


def test_changing_the_date_keeps_the_dating(management_client):
    item = _item_with_dating(management_client)
    new_date = DateFactory(date="c. 1160")

    response = management_client.patch(f"{ITEMS_URL}{item.pk}/", {"date": new_date.pk}, format="json")

    assert response.status_code == 200
    assert _dating(management_client.get(f"{ITEMS_URL}{item.pk}/")) == DATING


def test_the_dating_is_saved_on_an_item_with_no_date(management_client):
    item_type = HistoricalItem._meta.get_field("type").choices[0][0]

    response = management_client.post(ITEMS_URL, {"type": item_type, "date": None, **DATING}, format="json")

    assert response.status_code == 201
    detail = management_client.get(f"{ITEMS_URL}{response.data['id']}/")
    assert detail.data["date"] is None
    assert _dating(detail) == DATING


def test_deleting_the_date_keeps_the_dating(management_client):
    item = _item_with_dating(management_client)

    item.date.delete()

    detail = management_client.get(f"{ITEMS_URL}{item.pk}/")
    assert detail.data["date"] is None
    assert _dating(detail) == DATING


def test_both_apis_show_the_dating_and_empty_strings_when_there_is_none(management_client):
    item = _item_with_dating(management_client)
    part = item.itempart_set.get()
    blank_part = cast(ItemPart, ItemPartFactory())

    def public(part_id: int) -> dict:
        response = APIClient().get(f"/api/v1/manuscripts/item-parts/{part_id}/")
        assert response.status_code == 200
        return dict(response.data["historical_item"])

    assert _dating(management_client.get(f"{ITEMS_URL}{item.pk}/")) == DATING
    assert {key: public(part.pk)[key] for key in DATING} == DATING
    empty = {"probable_text_date": "", "dating_notes": ""}
    assert _dating(management_client.get(f"{ITEMS_URL}{blank_part.historical_item_id}/")) == empty
    assert {key: public(blank_part.pk)[key] for key in DATING} == empty


def test_writing_the_dating_does_not_echo_it_back(management_client):
    item = cast(ItemPart, ItemPartFactory()).historical_item

    response = management_client.patch(f"{ITEMS_URL}{item.pk}/", DATING, format="json")

    assert response.status_code == 200
    assert not set(DATING) & set(response.data)


def test_a_probable_date_longer_than_its_column_is_refused(management_client):
    item = cast(ItemPart, ItemPartFactory()).historical_item
    url = f"{ITEMS_URL}{item.pk}/"

    assert management_client.patch(url, {"probable_text_date": "x" * 100}, format="json").status_code == 200
    response = management_client.patch(url, {"probable_text_date": "x" * 101}, format="json")

    assert response.status_code == 400
    assert set(response.data) == {"probable_text_date"}

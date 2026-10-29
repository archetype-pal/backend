"""Public scribes and hands endpoints."""

import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.common.tests.query_counts import assert_query_count_constant
from apps.manuscripts.tests.factories import BibliographicSourceFactory, ItemPartFactory
from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory, ScribeFactory

pytestmark = pytest.mark.django_db


def test_scribe_detail_shows_its_period_as_text(api_client):
    scribe = ScribeFactory()

    response = api_client.get(f"/api/v1/scribes/{scribe.id}/")

    assert response.status_code == 200
    assert (response.data["id"], response.data["name"], response.data["period"]) == (
        scribe.id,
        scribe.name,
        scribe.period.date,
    )


def test_scribe_list_query_count_does_not_grow_with_rows(api_client):
    def add_scribes(n: int) -> None:
        for i in range(n):
            # Each row lists the scribe's idiographs; a scribe may have none yet.
            if i % 2:
                ScribeFactory()
            else:
                GraphFactory(hand=HandFactory(scribe=ScribeFactory()))

    assert_query_count_constant(api_client, "/api/v1/scribes/", add_scribes)


def test_hand_detail_shows_labels_not_ids(api_client):
    hand = HandFactory()
    HandDescriptionFactory(hand=hand, source=BibliographicSourceFactory(label="BL"), content="A round caroline hand.")
    HandDescriptionFactory(hand=hand, source=None, content="No known source.")

    response = api_client.get(f"/api/v1/hands/{hand.id}/")

    assert response.status_code == 200
    assert response.data["name"] == hand.name
    assert (response.data["place"], response.data["date"]) == (hand.place.name, hand.date.date)
    assert sorted((d["source_label"] or "", d["content"]) for d in response.data["descriptions"]) == [
        ("", "No known source."),
        ("BL", "A round caroline hand."),
    ]


def test_hand_list_query_count_does_not_grow_with_hands(api_client):
    assert_query_count_constant(api_client, "/api/v1/hands/", HandFactory.create_batch)


def test_hand_list_orders_by_default_priority_and_num(api_client):
    item_part = ItemPartFactory()
    low_order = HandFactory(item_part=item_part, name="B", num=2, priority=0)
    high_order = HandFactory(item_part=item_part, name="A", num=1, priority=0)
    preferred = HandFactory(item_part=item_part, name="C", num=99, priority=10)
    default = HandFactory(item_part=item_part, name="D", num=100, priority=0, is_default=True)

    response = api_client.get(f"/api/v1/hands/?item_part={item_part.id}")

    assert [row["id"] for row in response.data["results"]] == [default.id, preferred.id, high_order.id, low_order.id]


def test_hand_list_labels_the_manuscript_each_hand_sits_on(api_client):
    # The Scribe page labels each hand's manuscript with this (frontend#144).
    item_part = ItemPartFactory(current_item_locus="f. 1r")
    hand = HandFactory(item_part=item_part)

    response = api_client.get(f"/api/v1/hands/?scribe={hand.scribe_id}")

    current_item = item_part.current_item
    assert response.data["results"][0]["item_part_display_label"] == (
        f"{current_item.repository.label} {current_item.shelfmark} f. 1r"
    )

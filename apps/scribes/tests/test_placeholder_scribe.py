"""DigiPal's placeholder scribe (pk -1) is not shown as a scribe on the public site."""

import pytest

from apps.common.tests.factories import PlaceFactory
from apps.scribes.models import Scribe
from apps.scribes.tests.factories import HandFactory, ScribeFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def placeholder():
    return ScribeFactory(pk=-1, name="[name] update records relations later", scriptorium=None, period=None)


def test_only_the_placeholder_is_one():
    assert ScribeFactory.build(pk=-1).is_placeholder
    assert not ScribeFactory.build(pk=1).is_placeholder
    # Not yet saved, so not yet anything.
    assert not Scribe(name="New scribe").is_placeholder


def test_the_scribes_list_leaves_it_out(api_client, placeholder):
    real = ScribeFactory()

    response = api_client.get("/api/v1/scribes/")

    assert [row["id"] for row in response.data["results"]] == [real.id]


def test_it_has_no_page(api_client, placeholder):
    assert api_client.get("/api/v1/scribes/-1/").status_code == 404


def test_its_hands_have_no_scribe(api_client, placeholder):
    hand = HandFactory(scribe=placeholder)
    real = HandFactory(scribe=ScribeFactory(scriptorium=PlaceFactory(name="Melrose")))

    detail = api_client.get(f"/api/v1/hands/{hand.id}/").data
    rows = {row["id"]: row for row in api_client.get("/api/v1/hands/").data["results"]}

    assert (detail["scribe"], detail["scriptorium"]) == (None, "")
    assert (rows[hand.id]["scribe"], rows[hand.id]["scriptorium"]) == (None, "")
    assert (rows[real.id]["scribe"], rows[real.id]["scriptorium"]) == (real.scribe_id, "Melrose")


def test_the_backoffice_still_lists_it_with_its_hands(management_client, placeholder):
    # Editors reassign its hands from there.
    HandFactory.create_batch(2, scribe=placeholder)

    scribes = management_client.get("/api/v1/management/scribes/scribes/").json()["results"]
    hands = management_client.get("/api/v1/management/scribes/hands/", {"scribe": -1}).json()["results"]

    assert [(row["id"], row["hand_count"]) for row in scribes] == [(-1, 2)]
    assert [row["scribe"] for row in hands] == [-1, -1]


def test_the_public_hands_cannot_be_filtered_by_it(api_client, placeholder):
    HandFactory(scribe=placeholder)
    real = HandFactory(scribe=ScribeFactory())

    assert api_client.get("/api/v1/hands/", {"scribe": -1}).status_code == 400
    assert [row["id"] for row in api_client.get("/api/v1/hands/", {"scribe": real.scribe_id}).data["results"]] == [
        real.id
    ]

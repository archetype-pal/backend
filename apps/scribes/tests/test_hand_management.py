"""Management (backoffice) CRUD for Hand — archetype-pal/frontend#124."""

import pytest

from apps.common.tests.factories import PlaceFactory
from apps.manuscripts.tests.factories import ItemPartFactory
from apps.scribes.tests.factories import HandFactory, ScribeFactory


@pytest.mark.django_db
class TestHandManagementViewSet:
    def _url(self, pk=None):
        base = "/api/v1/management/scribes/hands/"
        return f"{base}{pk}/" if pk else base

    def test_description_is_not_required_on_create(self, management_client):
        scribe = ScribeFactory()
        item_part = ItemPartFactory()
        response = management_client.post(
            self._url(),
            data={"name": "New hand", "scribe": scribe.pk, "item_part": item_part.pk},
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["description"] == ""

    def test_description_can_be_cleared_on_update(self, management_client):
        hand = HandFactory(description="some legacy description")
        response = management_client.patch(self._url(hand.pk), data={"description": ""}, format="json")
        assert response.status_code == 200, response.json()
        hand.refresh_from_db()
        assert hand.description == ""

    def test_place_is_writable_by_id_and_exposes_a_display_name(self, management_client):
        hand = HandFactory(place=PlaceFactory(name="Canterbury"))
        response = management_client.get(self._url(hand.pk))
        assert response.status_code == 200
        assert response.json()["place"] == hand.place_id
        assert response.json()["place_display"] == "Canterbury"

        london = PlaceFactory(name="London")
        response = management_client.patch(self._url(hand.pk), data={"place": london.pk}, format="json")
        assert response.status_code == 200, response.json()
        hand.refresh_from_db()
        assert hand.place_id == london.pk

    def test_place_can_be_cleared_on_update(self, management_client):
        hand = HandFactory(place=PlaceFactory())
        response = management_client.patch(self._url(hand.pk), data={"place": None}, format="json")
        assert response.status_code == 200, response.json()
        hand.refresh_from_db()
        assert hand.place is None

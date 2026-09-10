"""Management (backoffice) CRUD for Hand — archetype-pal/frontend#124."""

import pytest

from apps.common.tests.factories import PlaceFactory
from apps.manuscripts.tests.factories import BibliographicSourceFactory, ItemPartFactory
from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory, ScribeFactory


@pytest.mark.django_db
class TestHandManagementViewSet:
    def _url(self, pk=None):
        base = "/api/v1/management/scribes/hands/"
        return f"{base}{pk}/" if pk else base

    def test_description_is_not_required_on_create(self, management_client):
        # A Hand's descriptions are a separate zero-or-more relation now, so
        # creating one requires no description at all.
        scribe = ScribeFactory()
        item_part = ItemPartFactory()
        response = management_client.post(
            self._url(),
            data={"name": "New hand", "scribe": scribe.pk, "item_part": item_part.pk},
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["descriptions"] == []

    def test_descriptions_are_nested_read_only_with_source_label(self, management_client):
        source = BibliographicSourceFactory(label="BL")
        hand = HandFactory()
        HandDescriptionFactory(hand=hand, source=source, content="A round caroline hand.")
        HandDescriptionFactory(hand=hand, source=None, content="No known source for this one.")

        response = management_client.get(self._url(hand.pk))
        assert response.status_code == 200
        descriptions = response.json()["descriptions"]
        assert len(descriptions) == 2
        assert {"source_label": "BL", "content": "A round caroline hand."} in [
            {"source_label": d["source_label"], "content": d["content"]} for d in descriptions
        ]
        assert any(d["source_label"] is None for d in descriptions)

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

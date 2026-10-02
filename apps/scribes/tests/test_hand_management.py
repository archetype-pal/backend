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

    def test_backoffice_save_sets_and_clears_the_hand_images(self, management_client):
        """The hand page PATCHes its whole form; the ticked images are what persists."""
        from apps.manuscripts.tests.factories import ItemImageFactory

        hand = HandFactory()
        ticked, unticked = ItemImageFactory(item_part=hand.item_part), ItemImageFactory(item_part=hand.item_part)
        form = {"name": hand.name, "place": hand.place_id, "date": hand.date_id}

        response = management_client.patch(
            self._url(hand.pk), data={**form, "item_part_images": [ticked.pk]}, format="json"
        )
        assert response.status_code == 200, response.json()
        assert response.json()["item_part_images"] == [ticked.pk]
        assert list(hand.item_part_images.values_list("pk", flat=True)) == [ticked.pk]
        assert unticked.pk not in management_client.get(self._url(hand.pk)).json()["item_part_images"]

        response = management_client.patch(self._url(hand.pk), data={**form, "item_part_images": []}, format="json")
        assert response.status_code == 200, response.json()
        assert not hand.item_part_images.exists()

    def test_ticked_images_scope_the_public_hand_list(self, api_client):
        """What the image viewer asks for: only hands ticked on that image."""
        from apps.manuscripts.tests.factories import ItemImageFactory

        hand = HandFactory()
        HandFactory(item_part=hand.item_part)  # same part, not ticked on the image
        image = ItemImageFactory(item_part=hand.item_part)
        hand.item_part_images.add(image)

        response = api_client.get(f"/api/v1/hands/?item_part={hand.item_part_id}&item_part_images={image.pk}")
        assert response.status_code == 200
        assert [row["id"] for row in response.json()["results"]] == [hand.pk]

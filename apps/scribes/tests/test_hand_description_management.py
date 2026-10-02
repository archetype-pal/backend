"""Management CRUD for HandDescription — archetype-pal/frontend#124.

A Hand can now have zero or more descriptions, each optionally citing a
BibliographicSource — replacing the old single mandatory description field
that couldn't record multiple descriptions or where any of them came from.
"""

import pytest

from apps.manuscripts.tests.factories import BibliographicSourceFactory
from apps.scribes.models import HandDescription
from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory


@pytest.mark.django_db
class TestHandDescriptionManagementViewSet:
    def _url(self, pk=None):
        base = "/api/v1/management/scribes/hand-descriptions/"
        return f"{base}{pk}/" if pk else base

    def test_create_without_a_source(self, management_client):
        hand = HandFactory()
        response = management_client.post(
            self._url(),
            data={"hand": hand.pk, "content": "A charter hand."},
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["source"] is None
        assert response.json()["source_label"] is None

    def test_create_with_a_source(self, management_client):
        hand = HandFactory()
        source = BibliographicSourceFactory(label="BL")
        response = management_client.post(
            self._url(),
            data={"hand": hand.pk, "source": source.pk, "content": "A charter hand."},
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert response.json()["source_label"] == "BL"

    def test_filter_by_hand(self, management_client):
        keep = HandDescriptionFactory()
        HandDescriptionFactory()  # different hand
        response = management_client.get(f"{self._url()}?hand={keep.hand_id}")
        assert response.status_code == 200
        rows = response.json()["results"]
        assert [r["id"] for r in rows] == [keep.pk]

    def test_update_content(self, management_client):
        description = HandDescriptionFactory(content="Old text")
        response = management_client.patch(self._url(description.pk), data={"content": "New text"}, format="json")
        assert response.status_code == 200, response.json()
        description.refresh_from_db()
        assert description.content == "New text"

    def test_delete(self, management_client):
        description = HandDescriptionFactory()
        response = management_client.delete(self._url(description.pk))
        assert response.status_code == 204
        assert not HandDescription.objects.filter(pk=description.pk).exists()

    def test_anonymous_denied(self, api_client):
        assert api_client.get(self._url()).status_code in (401, 403)

    def test_regular_user_denied(self, authenticated_client):
        hand = HandFactory()
        response = authenticated_client.post(self._url(), data={"hand": hand.pk, "content": "x"})
        assert response.status_code == 403

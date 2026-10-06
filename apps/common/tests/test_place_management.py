"""Management CRUD for the Place authority list — archetype-pal/frontend#124."""

from django.db import IntegrityError
import pytest

from apps.common.models import Place
from apps.common.tests.factories import PlaceFactory


@pytest.mark.django_db
class TestPlaceManagementViewSet:
    def _url(self, pk=None):
        base = "/api/v1/management/common/places/"
        return f"{base}{pk}/" if pk else base

    def test_create(self, management_client):
        response = management_client.post(self._url(), data={"name": "Canterbury"}, format="json")
        assert response.status_code == 201, response.json()
        assert response.json()["name"] == "Canterbury"

    def test_create_rejects_duplicate_name(self, management_client):
        PlaceFactory(name="London")
        response = management_client.post(self._url(), data={"name": "London"}, format="json")
        assert response.status_code == 400

    def test_create_rejects_duplicate_name_in_another_case(self, management_client):
        PlaceFactory(name="London")
        response = management_client.post(self._url(), data={"name": " london "}, format="json")
        assert response.status_code == 400
        assert "name" in response.json()

    def test_create_strips_surrounding_whitespace(self, management_client):
        response = management_client.post(self._url(), data={"name": "  Perth "}, format="json")
        assert response.status_code == 201
        assert response.json()["name"] == "Perth"

    def test_update_rejects_renaming_onto_another_place(self, management_client):
        PlaceFactory(name="London")
        place = PlaceFactory(name="Londun")
        response = management_client.patch(self._url(place.pk), data={"name": "LONDON"}, format="json")
        assert response.status_code == 400

    def test_update_may_change_only_the_case_of_its_own_name(self, management_client):
        place = PlaceFactory(name="london")
        response = management_client.patch(self._url(place.pk), data={"name": "London"}, format="json")
        assert response.status_code == 200
        place.refresh_from_db()
        assert place.name == "London"

    def test_database_rejects_a_case_variant(self):
        PlaceFactory(name="London")
        with pytest.raises(IntegrityError):
            Place.objects.create(name="LONDON")

    def test_list_is_unpaginated_and_ordered_by_name(self, management_client):
        PlaceFactory(name="York")
        PlaceFactory(name="Canterbury")
        response = management_client.get(self._url())
        assert response.status_code == 200
        names = [row["name"] for row in response.json()]
        assert names == ["Canterbury", "York"]

    def test_update(self, management_client):
        place = PlaceFactory(name="Londun")
        response = management_client.patch(self._url(place.pk), data={"name": "London"}, format="json")
        assert response.status_code == 200
        place.refresh_from_db()
        assert place.name == "London"

    def test_delete(self, management_client):
        place = PlaceFactory()
        response = management_client.delete(self._url(place.pk))
        assert response.status_code == 204
        assert not Place.objects.filter(pk=place.pk).exists()

    def test_anonymous_denied(self, api_client):
        assert api_client.get(self._url()).status_code in (401, 403)

    def test_regular_user_denied(self, authenticated_client):
        assert authenticated_client.post(self._url(), data={"name": "X"}).status_code == 403

import pytest
from rest_framework.test import APIClient

from apps.common.models import SiteLabels
from apps.users.tests.factories import SuperuserFactory, UserFactory

URL = "/api/v1/site-labels/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_labels(labels: dict) -> SiteLabels:
    """Set the singleton row's content. A row already exists from the
    0009_seed_sitelabels_defaults migration, so update it rather than
    creating a fresh pk=1 row (which would collide)."""
    instance = SiteLabels.get_solo()
    instance.labels = labels
    instance.save()
    return instance


@pytest.mark.django_db
class TestSiteLabelsGet:
    def test_anonymous_can_read(self, api_client):
        set_labels({})
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data["labels"] == {}

    def test_returns_stored_labels(self, api_client):
        set_labels({"siteTitle": {"en": "Hi", "fr": "Salut"}})
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data["labels"] == {"siteTitle": {"en": "Hi", "fr": "Salut"}}

    def test_read_does_not_create_extra_rows(self, api_client):
        assert SiteLabels.objects.count() == 1
        api_client.get(URL)
        assert SiteLabels.objects.count() == 1


@pytest.mark.django_db
class TestSiteLabelsPut:
    def test_anonymous_cannot_write(self, api_client):
        response = api_client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 401

    def test_regular_user_cannot_write(self):
        client = client_for(UserFactory())
        response = client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 403

    def test_superuser_can_write(self):
        client = client_for(SuperuserFactory())
        response = client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 200
        assert response.data["labels"] == {"siteTitle": {"en": "Hi", "fr": "Salut"}}
        assert SiteLabels.get_solo().labels == {"siteTitle": {"en": "Hi", "fr": "Salut"}}

    def test_write_replaces_existing_row(self):
        set_labels({"siteTitle": {"en": "Old", "fr": "Vieux"}})
        client = client_for(SuperuserFactory())
        response = client.put(URL, {"labels": {"siteTitle": {"en": "New", "fr": "Nouveau"}}}, format="json")
        assert response.status_code == 200
        assert SiteLabels.objects.count() == 1
        assert SiteLabels.get_solo().labels == {"siteTitle": {"en": "New", "fr": "Nouveau"}}

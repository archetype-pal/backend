import json
from typing import cast

import pytest
from rest_framework.test import APIClient

from apps.common.models import AppSettings, EditEvent
from apps.common.views import DEFAULT_SITE_FEATURES, SITE_FEATURES_KEY
from apps.users.tests.factories import SuperuserFactory, UserFactory

URL = "/api/v1/site-features/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_site_features(value: dict, *, is_active: bool = True) -> AppSettings:
    instance, _ = AppSettings.objects.update_or_create(
        key=SITE_FEATURES_KEY, defaults={"value": json.dumps(value), "is_active": is_active}
    )
    return cast(AppSettings, instance)


@pytest.mark.django_db
class TestSiteFeaturesGet:
    def test_anonymous_can_read(self, api_client):
        # The seed migration (0010_seed_site_features.py) pre-populates the row.
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_returns_stored_config(self, api_client):
        custom = {"sections": {"search": False}, "searchCategories": {}}
        set_site_features(custom)

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == custom

    def test_falls_back_to_default_when_row_missing(self, api_client):
        AppSettings.objects.filter(key=SITE_FEATURES_KEY).delete()

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_falls_back_to_default_when_row_inactive(self, api_client):
        set_site_features({"sections": {"search": False}, "searchCategories": {}}, is_active=False)

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_falls_back_to_default_when_value_is_not_valid_json(self, api_client):
        AppSettings.objects.update_or_create(key=SITE_FEATURES_KEY, defaults={"value": "not json", "is_active": True})

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES


@pytest.mark.django_db
class TestSiteFeaturesPut:
    valid_payload = {"sections": {"search": False}, "sectionOrder": ["search"], "searchCategories": {}}

    def test_anonymous_cannot_write(self, api_client):
        response = api_client.put(URL, self.valid_payload, format="json")
        assert response.status_code == 401

    def test_regular_user_cannot_write(self):
        client = client_for(UserFactory())
        response = client.put(URL, self.valid_payload, format="json")
        assert response.status_code == 403

    def test_superuser_can_write(self):
        client = client_for(SuperuserFactory())

        response = client.put(URL, self.valid_payload, format="json")

        assert response.status_code == 200
        assert response.data == self.valid_payload
        row = AppSettings.objects.get(key=SITE_FEATURES_KEY)
        assert json.loads(row.value) == self.valid_payload
        assert row.is_active is True

    def test_get_reflects_put(self):
        client = client_for(SuperuserFactory())
        client.put(URL, self.valid_payload, format="json")

        response = APIClient().get(URL)

        assert response.status_code == 200
        assert response.data == self.valid_payload

    @pytest.mark.parametrize(
        "payload",
        [
            "a plain string",
            42,
            ["sections", "searchCategories"],
            {},
            {"sections": {}},
            {"searchCategories": {}},
        ],
    )
    def test_missing_or_invalid_shape_is_rejected(self, payload):
        client = client_for(SuperuserFactory())
        original = AppSettings.objects.filter(key=SITE_FEATURES_KEY).first()

        response = client.put(URL, payload, format="json")

        assert response.status_code == 400
        current = AppSettings.objects.filter(key=SITE_FEATURES_KEY).first()
        if original is None:
            assert current is None
        else:
            assert current.value == original.value

    def test_write_creates_audit_event(self):
        client = client_for(SuperuserFactory())

        response = client.put(URL, self.valid_payload, format="json")

        assert response.status_code == 200
        row = AppSettings.objects.get(key=SITE_FEATURES_KEY)
        event = EditEvent.objects.filter(target_type="appsettings", target_id=row.pk).latest("created")
        assert event.actor is not None

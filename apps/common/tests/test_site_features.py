import json

import pytest
from rest_framework.test import APIClient

from apps.common.models import AppSettings, EditEvent
from apps.common.views import (
    DEFAULT_SITE_FEATURES,
    SITE_FEATURES_KEY_PREFIX,
    flatten_settings,
)
from apps.users.tests.factories import SuperuserFactory, UserFactory

URL = "/api/v1/app-settings/"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_site_features(value: dict, *, is_active: bool = True, is_public: bool = True) -> None:
    """Seed one AppSettings row per leaf key, matching how SiteFeaturesView.put stores it."""
    AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX).delete()
    for dotted_key, leaf_value in flatten_settings(value).items():
        AppSettings.objects.create(
            key=f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}",
            value=json.dumps(leaf_value),
            is_active=is_active,
            is_public=is_public,
        )


@pytest.mark.django_db
class TestSiteFeaturesGet:
    def test_anonymous_can_read(self, api_client):
        # The seed migration (0010_seed_site_features.py) pre-populates the per-key rows.
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_returns_stored_config(self, api_client):
        custom = {
            "sections": {"search": False},
            "sectionOrder": ["search"],
            "searchCategories": {"manuscripts": {"enabled": False}},
        }
        set_site_features(custom)

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == custom

    def test_falls_back_to_default_when_no_rows(self, api_client):
        AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX).delete()

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_falls_back_to_default_when_all_rows_inactive(self, api_client):
        set_site_features({"sections": {"search": False}, "searchCategories": {}}, is_active=False)

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_excludes_rows_not_marked_public(self, api_client):
        # `is_public` is the enforced visibility boundary (not the key prefix):
        # an active row under `site_features.*` that isn't flagged public must
        # still never reach an anonymous caller.
        set_site_features({"sections": {"search": False}, "searchCategories": {}}, is_public=False)

        response = api_client.get(URL)

        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES

    def test_skips_corrupt_row_but_keeps_the_rest(self, api_client):
        set_site_features({"sections": {"search": False, "collection": True}, "searchCategories": {}})
        AppSettings.objects.filter(key=f"{SITE_FEATURES_KEY_PREFIX}sections.search").update(value="not json")

        response = api_client.get(URL)

        assert response.status_code == 200
        # `searchCategories: {}` has no leaves and never round-trips (nothing to
        # store), which is fine: an empty map carries no information either way.
        assert response.data == {"sections": {"collection": True}}


@pytest.mark.django_db
class TestSiteFeaturesPut:
    # `searchCategories: {}` is intentionally omitted from what we assert
    # round-trips: an empty map has no leaf keys, so nothing is stored for it
    # and it doesn't reappear on GET (see TestSiteFeaturesGet's note on this).
    valid_payload = {"sections": {"search": False}, "sectionOrder": ["search"], "searchCategories": {}}
    expected_stored = {"sections": {"search": False}, "sectionOrder": ["search"]}

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
        assert response.data == self.expected_stored
        row = AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sections.search")
        assert row.value == "false"
        assert row.is_public is True
        assert AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sectionOrder").value == '["search"]'

    def test_write_deletes_rows_for_keys_no_longer_present(self):
        client = client_for(SuperuserFactory())
        set_site_features({"sections": {"search": False, "collection": True}, "searchCategories": {}})

        response = client.put(URL, self.valid_payload, format="json")

        assert response.status_code == 200
        assert not AppSettings.objects.filter(key=f"{SITE_FEATURES_KEY_PREFIX}sections.collection").exists()

    def test_get_reflects_put(self):
        client = client_for(SuperuserFactory())
        client.put(URL, self.valid_payload, format="json")

        response = APIClient().get(URL)

        assert response.status_code == 200
        assert response.data == self.expected_stored

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
        set_site_features(self.valid_payload)
        before = {row.key: row.value for row in AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX)}

        response = client.put(URL, payload, format="json")

        assert response.status_code == 400
        after = {row.key: row.value for row in AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX)}
        assert after == before

    def test_write_creates_audit_events_per_key(self):
        client = client_for(SuperuserFactory())

        response = client.put(URL, self.valid_payload, format="json")

        assert response.status_code == 200
        row = AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sections.search")
        event = EditEvent.objects.filter(target_type="appsettings", target_id=row.pk).latest("created")
        assert event.actor is not None

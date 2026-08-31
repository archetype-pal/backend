from typing import cast

import pytest
from rest_framework.test import APIClient

from apps.common.models import EditEvent, SiteLabel
from apps.users.tests.factories import SuperuserFactory, UserFactory

URL = "/api/v1/site-labels/"

# The seed migration (0008_sitelabel_per_key) pre-populates all 22 keys, so
# every test starts from that baseline rather than an empty table.
SEEDED_KEY_COUNT = len(SiteLabel.Key.values)


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_label(key: str, value: dict) -> SiteLabel:
    instance, _ = SiteLabel.objects.update_or_create(key=key, defaults={"value": value})
    return cast(SiteLabel, instance)


@pytest.mark.django_db
class TestSiteLabelsGet:
    def test_anonymous_can_read(self, api_client):
        response = api_client.get(URL)
        assert response.status_code == 200
        assert set(response.data["labels"]) == set(SiteLabel.Key.values)

    def test_returns_stored_labels(self, api_client):
        set_label("siteTitle", {"en": "Hi", "fr": "Salut"})
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data["labels"]["siteTitle"] == {"en": "Hi", "fr": "Salut"}

    def test_read_does_not_create_extra_rows(self, api_client):
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT
        api_client.get(URL)
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT

    def test_seeded_labels_include_german(self, api_client):
        # 0012_seed_sitelabel_german backfills "de" into every seeded row.
        response = api_client.get(URL)
        assert response.status_code == 200
        for key, value in response.data["labels"].items():
            assert "de" in value, f"{key} is missing a German value"


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
        assert response.data["labels"]["siteTitle"] == {"en": "Hi", "fr": "Salut"}
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "Hi", "fr": "Salut"}

    def test_write_updates_only_targeted_key(self):
        set_label("footerLine1", {"en": "Footer", "fr": "Pied de page"})
        client = client_for(SuperuserFactory())

        response = client.put(URL, {"labels": {"siteTitle": {"en": "New", "fr": "Nouveau"}}}, format="json")

        assert response.status_code == 200
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "New", "fr": "Nouveau"}
        # The old singleton's full-blob PUT used to wipe every key absent from
        # the payload — this is the regression test proving that's fixed.
        assert SiteLabel.objects.get(key="footerLine1").value == {"en": "Footer", "fr": "Pied de page"}

    def test_unknown_key_is_rejected(self):
        client = client_for(SuperuserFactory())
        response = client.put(URL, {"labels": {"notARealKey": {"en": "x", "fr": "y"}}}, format="json")
        assert response.status_code == 400
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT
        assert not SiteLabel.objects.filter(key="notARealKey").exists()

    @pytest.mark.parametrize("value", ["a plain string", 42, ["en", "fr"], {"en": 1, "fr": "Salut"}])
    def test_non_mapping_value_is_rejected(self, value):
        set_label("siteTitle", {"en": "Original", "fr": "Original"})
        client = client_for(SuperuserFactory())

        response = client.put(URL, {"labels": {"siteTitle": value}}, format="json")

        assert response.status_code == 400
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "Original", "fr": "Original"}

    def test_empty_mapping_is_rejected(self):
        # `{}` satisfies isinstance(dict) and vacuously satisfies the per-value
        # string check, so without an explicit guard it would blank the label.
        set_label("siteTitle", {"en": "Original", "fr": "Original"})
        client = client_for(SuperuserFactory())

        response = client.put(URL, {"labels": {"siteTitle": {}}}, format="json")

        assert response.status_code == 400
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "Original", "fr": "Original"}

    def test_write_creates_audit_event(self):
        client = client_for(SuperuserFactory())
        response = client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 200

        row = SiteLabel.objects.get(key="siteTitle")
        event = EditEvent.objects.filter(target_type="sitelabel", target_id=row.pk).latest("created")
        assert event.summary == "siteTitle"
        assert event.actor is not None

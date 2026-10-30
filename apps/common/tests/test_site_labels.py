from typing import cast

import pytest

from apps.common.models import EditEvent, SiteLabel

URL = "/api/v1/site-labels/"

# The seed migration (0008_sitelabel_per_key) pre-populates all 22 keys, so
# every test starts from that baseline rather than an empty table.
SEEDED_KEY_COUNT = len(SiteLabel.Key.values)


def set_label(key: str, value: dict) -> SiteLabel:
    instance, _ = SiteLabel.objects.update_or_create(key=key, defaults={"value": value})
    return cast(SiteLabel, instance)


@pytest.mark.django_db
class TestSiteLabelsGet:
    def test_anonymous_can_read_every_seeded_key(self, api_client):
        response = api_client.get(URL)
        assert response.status_code == 200
        assert set(response.data["labels"]) == set(SiteLabel.Key.values)
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT  # a read never creates rows

    def test_returns_stored_labels(self, api_client):
        set_label("siteTitle", {"en": "Hi", "fr": "Salut"})
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data["labels"]["siteTitle"] == {"en": "Hi", "fr": "Salut"}


@pytest.mark.django_db
class TestSiteLabelsPut:
    def test_anonymous_cannot_write(self, api_client):
        response = api_client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 401

    def test_regular_user_cannot_write(self, authenticated_client):
        response = authenticated_client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 403

    def test_superuser_can_write(self, management_client):
        response = management_client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 200
        assert response.data["labels"]["siteTitle"] == {"en": "Hi", "fr": "Salut"}
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "Hi", "fr": "Salut"}

    def test_write_updates_only_targeted_key(self, management_client):
        set_label("footerLine1", {"en": "Footer", "fr": "Pied de page"})

        response = management_client.put(URL, {"labels": {"siteTitle": {"en": "New", "fr": "Nouveau"}}}, format="json")

        assert response.status_code == 200
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "New", "fr": "Nouveau"}
        # The old singleton's full-blob PUT used to wipe every key absent from
        # the payload — this is the regression test proving that's fixed.
        assert SiteLabel.objects.get(key="footerLine1").value == {"en": "Footer", "fr": "Pied de page"}

    def test_unknown_key_is_rejected(self, management_client):
        response = management_client.put(URL, {"labels": {"notARealKey": {"en": "x", "fr": "y"}}}, format="json")
        assert response.status_code == 400
        assert SiteLabel.objects.count() == SEEDED_KEY_COUNT
        assert not SiteLabel.objects.filter(key="notARealKey").exists()

    @pytest.mark.parametrize("value", ["a plain string", 42, ["en", "fr"], {"en": 1, "fr": "Salut"}])
    def test_non_mapping_value_is_rejected(self, value, management_client):
        set_label("siteTitle", {"en": "Original", "fr": "Original"})

        response = management_client.put(URL, {"labels": {"siteTitle": value}}, format="json")

        assert response.status_code == 400
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "Original", "fr": "Original"}

    def test_empty_mapping_is_rejected(self, management_client):
        # `{}` satisfies isinstance(dict) and vacuously satisfies the per-value
        # string check, so without an explicit guard it would blank the label.
        set_label("siteTitle", {"en": "Original", "fr": "Original"})

        response = management_client.put(URL, {"labels": {"siteTitle": {}}}, format="json")

        assert response.status_code == 400
        assert SiteLabel.objects.get(key="siteTitle").value == {"en": "Original", "fr": "Original"}

    @pytest.mark.parametrize("link", ["/about/project", "https://example.org/about", ""])
    def test_link_key_accepts_paths_and_http_urls(self, link, management_client):
        response = management_client.put(URL, {"labels": {"homeAboutUrl": {"en": link, "fr": link}}}, format="json")
        assert response.status_code == 200
        assert SiteLabel.objects.get(key="homeAboutUrl").value == {"en": link, "fr": link}

    @pytest.mark.parametrize("link", ["javascript:alert(1)", "//evil.example", "/\\evil.example", "about/project"])
    def test_link_key_rejects_unsafe_targets(self, link, management_client):
        set_label("homeContextUrl", {"en": "/about/context"})

        response = management_client.put(URL, {"labels": {"homeContextUrl": {"en": "/ok", "fr": link}}}, format="json")

        assert response.status_code == 400
        assert SiteLabel.objects.get(key="homeContextUrl").value == {"en": "/about/context"}

    def test_write_creates_audit_event(self, management_client):
        response = management_client.put(URL, {"labels": {"siteTitle": {"en": "Hi", "fr": "Salut"}}}, format="json")
        assert response.status_code == 200

        row = SiteLabel.objects.get(key="siteTitle")
        event = EditEvent.objects.filter(target_type="sitelabel", target_id=row.pk).latest("created")
        assert event.summary == "siteTitle"
        assert event.actor is not None

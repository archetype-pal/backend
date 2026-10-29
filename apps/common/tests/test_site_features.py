import json
from typing import Any

import pytest

from apps.common.models import AppSettings, EditEvent
from apps.common.services.site_features import (
    DEFAULT_SITE_FEATURES,
    SITE_FEATURES_KEY_PREFIX,
    flatten_settings,
)

URL = "/api/v1/app-settings/"

VALID_PAYLOAD: dict[str, Any] = {
    "sections": {"search": False},
    "sectionOrder": ["search"],
    "features": {"manuscriptDescriptions": False},
    "theme": {
        "primaryColor": "#123456",
        "primaryForegroundColor": "#abcdef",
        "accentColor": "#654321",
        "titleBarBackgroundColor": "#111111",
        "titleBarTextColor": "#eeeeee",
        "navBarBackgroundColor": "#222222",
        "navBarTextColor": "#dddddd",
    },
    "branding": {"logoUrl": "https://example.org/logo.png"},
    "searchCategories": {
        "manuscripts": {"enabled": False, "visibleColumns": ["Shelfmark"], "visibleFacets": []},
    },
}


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
def test_seed_migration_wrote_a_row_per_leaf():
    # Key set, not a count: a seed writing the right number of rows under a
    # typo'd prefix would otherwise ship green, because GET's fallback returns
    # exactly what `test_anonymous_can_read` asserts.
    stored = AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX, is_public=True)
    assert {row.key for row in stored} == {
        f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}" for dotted_key in flatten_settings(DEFAULT_SITE_FEATURES)
    }


@pytest.mark.django_db
class TestSiteFeaturesGet:
    def test_anonymous_can_read(self, api_client):
        # The seed migration (0010_seed_site_features.py) pre-populates the per-key rows.
        response = api_client.get(URL)
        assert response.status_code == 200
        assert response.data == DEFAULT_SITE_FEATURES
        # Pinned literally, not via the constant: this is the frontend's fourth
        # top-level key, and both backend copies of the defaults omitted it.
        assert response.data["features"] == {"manuscriptDescriptions": True}

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

    def test_skips_conflicting_key_but_keeps_the_rest(self, api_client):
        # A row directly under `sections` collides with the `sections.search`/
        # `sections.collection` rows created below — `flatten_settings` can
        # never produce this pairing itself, only a bug or a hand-added row
        # can. `unflatten_settings` must drop the malformed subtree instead of
        # crashing the whole response (see its docstring). Created first, so
        # it's iterated (and claims `nested["sections"]` as a leaf) before the
        # rows that try to descend into it — the ordering that reproduces the
        # crash this test guards against.
        AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX).delete()
        AppSettings.objects.create(
            key=f"{SITE_FEATURES_KEY_PREFIX}sections",
            value=json.dumps(True),
            is_active=True,
            is_public=True,
        )
        rest = flatten_settings({"sections": {"search": False, "collection": True}, "sectionOrder": ["search"]})
        for dotted_key, leaf_value in rest.items():
            AppSettings.objects.create(
                key=f"{SITE_FEATURES_KEY_PREFIX}{dotted_key}",
                value=json.dumps(leaf_value),
                is_active=True,
                is_public=True,
            )

        response = api_client.get(URL)

        assert response.status_code == 200
        # The malformed scalar is the row that loses, not the valid subtree below it.
        assert response.data == {"sections": {"search": False, "collection": True}, "sectionOrder": ["search"]}


@pytest.mark.django_db
class TestSiteFeaturesPut:
    def test_anonymous_cannot_write(self, api_client):
        response = api_client.put(URL, VALID_PAYLOAD, format="json")
        assert response.status_code == 401

    def test_regular_user_cannot_write(self, authenticated_client):
        response = authenticated_client.put(URL, VALID_PAYLOAD, format="json")
        assert response.status_code == 403

    def test_superuser_can_write_and_anonymous_reads_it_back(self, management_client, api_client):
        response = management_client.put(URL, VALID_PAYLOAD, format="json")

        assert response.status_code == 200
        assert response.data == VALID_PAYLOAD
        assert api_client.get(URL).data == VALID_PAYLOAD
        # One public row per leaf, JSON-encoded.
        row = AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sections.search")
        assert (row.value, row.is_public) == ("false", True)
        assert AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sectionOrder").value == '["search"]'

    def test_write_deletes_rows_for_keys_no_longer_present(self, management_client):
        set_site_features({"sections": {"search": False, "collection": True}})

        response = management_client.put(URL, VALID_PAYLOAD, format="json")

        assert response.status_code == 200
        assert not AppSettings.objects.filter(key=f"{SITE_FEATURES_KEY_PREFIX}sections.collection").exists()

    @pytest.mark.parametrize(
        "payload",
        [
            "a plain string",
            42,
            ["sections", "searchCategories"],
            {},
            {"sections": {}},
            {"searchCategories": {}},
            # Both keys present but empty: accepted before, and it deleted every
            # stored row, after which GET re-enabled every section from the defaults.
            {"sections": {}, "searchCategories": {}},
            {**VALID_PAYLOAD, "sections": {}},
            {**VALID_PAYLOAD, "sections": True},
            {**VALID_PAYLOAD, "searchCategories": {"manuscripts": {"enabled": False}}},
            {key: value for key, value in VALID_PAYLOAD.items() if key != "sectionOrder"},
            {key: value for key, value in VALID_PAYLOAD.items() if key != "features"},
            {key: value for key, value in VALID_PAYLOAD.items() if key != "theme"},
            {key: value for key, value in VALID_PAYLOAD.items() if key != "branding"},
            # Unknown keys used to round-trip; DRF drops them, and the full
            # replace then deletes their stored rows behind a 200.
            {**VALID_PAYLOAD, "brandNewKey": {"nested": True}},
            # Missing/unknown branding sub-key.
            {**VALID_PAYLOAD, "branding": {}},
            {**VALID_PAYLOAD, "branding": {"logoUrl": "https://example.org/logo.png", "iconUrl": "x"}},
            {
                **VALID_PAYLOAD,
                "searchCategories": {
                    "manuscripts": {"enabled": False, "visibleColumns": [], "visibleFacets": [], "sortOrder": 1}
                },
            },
            # Not a 6-digit hex colour.
            {**VALID_PAYLOAD, "theme": {**VALID_PAYLOAD["theme"], "primaryColor": "blue"}},
            {**VALID_PAYLOAD, "theme": {**VALID_PAYLOAD["theme"], "accentColor": "#fff"}},
            # Missing/unknown theme sub-key.
            {**VALID_PAYLOAD, "theme": {"primaryColor": VALID_PAYLOAD["theme"]["primaryColor"]}},
            {**VALID_PAYLOAD, "theme": {**VALID_PAYLOAD["theme"], "backgroundColor": "#000000"}},
            # `AppSettings.key` is 255 chars and `update_or_create` skips
            # `full_clean`, so an over-long key is a Postgres DataError -> 500.
            {**VALID_PAYLOAD, "sections": {"x" * 300: True}},
        ],
    )
    def test_missing_or_invalid_shape_is_rejected(self, payload, management_client):
        set_site_features(VALID_PAYLOAD)
        before = {row.key: row.value for row in AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX)}

        response = management_client.put(URL, payload, format="json")

        assert response.status_code == 400
        after = {row.key: row.value for row in AppSettings.objects.filter(key__startswith=SITE_FEATURES_KEY_PREFIX)}
        assert after == before

    def test_form_encoded_body_is_rejected(self, management_client):
        # All six keys are present, so the rejection isolates the QueryDict
        # itself: `isinstance(QueryDict(...), dict)` is True, and DRF's HTML
        # input handling turns each one into an empty prefix-scoped dict.
        set_site_features(VALID_PAYLOAD)

        response = management_client.put(
            URL,
            {
                "sections": "on",
                "sectionOrder": "search",
                "features": "on",
                "theme": "on",
                "branding": "on",
                "searchCategories": "on",
            },
            format="multipart",
        )

        assert response.status_code == 400
        assert AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sections.search").value == "false"

    def test_write_creates_audit_events_per_key(self, management_client):

        response = management_client.put(URL, VALID_PAYLOAD, format="json")

        assert response.status_code == 200
        row = AppSettings.objects.get(key=f"{SITE_FEATURES_KEY_PREFIX}sections.search")
        event = EditEvent.objects.filter(target_type="appsettings", target_id=row.pk).latest("created")
        assert event.actor is not None

    def test_rewriting_an_identical_config_audits_nothing(self, management_client):
        management_client.put(URL, VALID_PAYLOAD, format="json")
        before = EditEvent.objects.filter(target_type="appsettings").count()

        response = management_client.put(URL, VALID_PAYLOAD, format="json")

        assert response.status_code == 200
        assert EditEvent.objects.filter(target_type="appsettings").count() == before

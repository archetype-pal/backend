"""0021 shows the charter-role facets on a site whose facet list predates them."""

from importlib import import_module
import json

from django.apps import apps
import pytest

from apps.common.models import AppSettings
from apps.common.services.site_features import DEFAULT_SITE_FEATURES

migration = import_module("apps.common.migrations.0021_append_charter_role_facets")

pytestmark = pytest.mark.django_db

KEY = "site_features.searchCategories.texts.visibleFacets"
ROLES = ["granters", "beneficiaries", "witnesses"]


def _store(value) -> None:
    AppSettings.objects.update_or_create(key=KEY, defaults={"value": json.dumps(value), "is_public": True})


def _stored():
    return json.loads(AppSettings.objects.get(key=KEY).value)


def test_a_fresh_site_lists_them_after_people():
    # Seeded by 0010, not appended by 0021.
    expected = ["text_date", "text_type", "type", "repository_city", "repository_name", "status", "language"]
    assert _stored() == [*expected, "places", "people", *ROLES]
    assert DEFAULT_SITE_FEATURES["searchCategories"]["texts"]["visibleFacets"] == _stored()


def test_appends_them_after_people_and_keeps_what_an_admin_hid():
    # This admin hid the language facet before the roles existed.
    _store(["text_date", "text_type", "places", "people", "status"])

    migration.append_charter_role_facets(apps, None)

    assert _stored() == ["text_date", "text_type", "places", "people", *ROLES, "status"]


def test_appends_them_at_the_end_when_people_is_hidden():
    _store(["text_date", "places"])

    migration.append_charter_role_facets(apps, None)

    assert _stored() == ["text_date", "places", *ROLES]


def test_adds_only_the_ones_missing():
    # An admin who listed one already, by hand, keeps it where they put it.
    _store(["witnesses", "people"])

    migration.append_charter_role_facets(apps, None)

    assert _stored() == ["witnesses", "people", "granters", "beneficiaries"]


@pytest.mark.parametrize("value", ["not json", json.dumps({"people": True})])
def test_leaves_a_row_it_cannot_read_alone(value):
    AppSettings.objects.update_or_create(key=KEY, defaults={"value": value})

    migration.append_charter_role_facets(apps, None)

    assert AppSettings.objects.get(key=KEY).value == value


def test_does_nothing_without_a_stored_list():
    AppSettings.objects.filter(key=KEY).delete()

    migration.append_charter_role_facets(apps, None)

    assert not AppSettings.objects.filter(key=KEY).exists()


def test_reversing_removes_only_them():
    _store(["people", *ROLES, "status"])

    migration.remove_charter_role_facets(apps, None)

    assert _stored() == ["people", "status"]

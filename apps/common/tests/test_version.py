from django.test import override_settings
from django.urls import reverse
import pytest


@pytest.mark.django_db
def test_version_reports_the_baked_build(api_client):
    with override_settings(APP_VERSION="2026.09.08.1022", APP_COMMIT="e4447fa"):
        response = api_client.get(reverse("version"))

    assert response.status_code == 200
    assert response.json() == {"version": "2026.09.08.1022", "commit": "e4447fa"}


@pytest.mark.django_db
def test_version_is_public(api_client):
    # The endpoint exists to answer "what is deployed right now", which is only
    # useful if an unauthenticated caller can ask.
    assert api_client.get(reverse("version")).status_code == 200


@pytest.mark.django_db
def test_version_falls_back_outside_a_published_build(api_client):
    # A source checkout has no build args, so the defaults must be reportable
    # rather than a 500 or an empty string.
    response = api_client.get(reverse("version"))

    assert response.json()["version"]
    assert response.json()["commit"]

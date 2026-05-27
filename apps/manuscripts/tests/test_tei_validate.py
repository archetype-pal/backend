"""Tests for TEI well-formedness validation (Phase H.10)."""

import pytest

from apps.manuscripts.services.tei import validate_tei_wellformed

pytestmark = pytest.mark.django_db

VALIDATE_URL = "/api/v1/manuscripts/image-texts/validate-tei/"


def test_valid_fragment_has_no_errors():
    assert validate_tei_wellformed('<p><seg type="address">x</seg></p>') == []


def test_empty_is_valid():
    assert validate_tei_wellformed("") == []


def test_mismatched_tag_reported():
    errors = validate_tei_wellformed("<p><seg>x</p></seg>")
    assert len(errors) == 1
    assert "mismatched tag" in errors[0]["message"]
    assert errors[0]["line"] == 1


def test_undefined_entity_reported():
    # HTML entities are invalid XML — a good thing to catch in the editor.
    errors = validate_tei_wellformed("<p>a&nbsp;b</p>")
    assert len(errors) == 1


def test_endpoint_valid(management_client):
    res = management_client.post(VALIDATE_URL, {"content": "<p><seg>x</seg></p>"}, format="json")
    assert res.status_code == 200
    assert res.data == {"valid": True, "errors": []}


def test_endpoint_invalid(management_client):
    res = management_client.post(VALIDATE_URL, {"content": "<p><seg>x</p>"}, format="json")
    assert res.status_code == 200
    assert res.data["valid"] is False
    assert len(res.data["errors"]) == 1


def test_endpoint_requires_auth(api_client):
    assert api_client.post(VALIDATE_URL, {"content": "<p>x</p>"}, format="json").status_code == 401

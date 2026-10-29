"""Tests for IIIF image dimension resolution (retry + fallback logging)."""

import io
import json
import logging
from unittest.mock import patch

import pytest

from apps.manuscripts.services.iiif import FALLBACK_IMAGE_DIMS, _fetch_info_dimensions, resolve_image_dimensions


@pytest.fixture(autouse=True)
def _clear_dimension_cache():
    """`_fetch_info_dimensions` is `lru_cache`d; keep tests independent of run order."""
    _fetch_info_dimensions.cache_clear()
    yield
    _fetch_info_dimensions.cache_clear()


def _info_response(width, height):
    # io.BytesIO already implements the context-manager protocol (IOBase),
    # so it works directly as the `with urlopen(...) as resp:` target.
    body = json.dumps({"width": width, "height": height}).encode()
    return io.BytesIO(body)


def test_resolves_real_dimensions_on_first_try():
    with patch("urllib.request.urlopen", return_value=_info_response(4000, 6000)) as mock_urlopen:
        assert resolve_image_dimensions("http://sipi/image-a") == (4000, 6000)
    assert mock_urlopen.call_count == 1


def test_retries_once_after_a_transient_failure_then_succeeds():
    responses = [TimeoutError("timed out")]

    def fake_urlopen(*args, **kwargs):
        if responses:
            raise responses.pop(0)
        return _info_response(2000, 3000)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), patch("time.sleep"):
        assert resolve_image_dimensions("http://sipi/image-b") == (2000, 3000)


def test_falls_back_and_logs_a_warning_after_exhausting_retries(caplog):
    with (
        patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
        patch("time.sleep"),
        caplog.at_level(logging.WARNING, logger="apps.manuscripts.services.iiif"),
    ):
        assert resolve_image_dimensions("http://sipi/unreachable") == FALLBACK_IMAGE_DIMS

    assert any("unreachable" in record.getMessage() for record in caplog.records)


def test_malformed_response_falls_back_without_retrying():
    with patch("urllib.request.urlopen", return_value=io.BytesIO(b"not json")) as mock_urlopen:
        assert resolve_image_dimensions("http://sipi/broken") == FALLBACK_IMAGE_DIMS
    # Malformed JSON can't be fixed by retrying, so only one attempt is made.
    assert mock_urlopen.call_count == 1


PUBLIC, INTERNAL = "http://localhost:8182", "http://image_server:1024"


@pytest.mark.parametrize(
    ("public_host", "internal_host", "identifier", "expected_url"),
    [
        # Same host on both sides: nothing to rewrite.
        (PUBLIC, PUBLIC, f"{PUBLIC}/abc", f"{PUBLIC}/abc/info.json"),
        # The identifier is built from the browser-facing IIIF_HOST; the server-to-server
        # fetch must go to IIIF_INTERNAL_HOST, trailing slashes or not.
        (PUBLIC, INTERNAL, f"{PUBLIC}/a/b", f"{INTERNAL}/a/b/info.json"),
        (f"{PUBLIC}/", f"{INTERNAL}/", f"{PUBLIC}/abc", f"{INTERNAL}/abc/info.json"),
        # An identifier not under IIIF_HOST is passed through rather than mis-rewritten.
        (PUBLIC, INTERNAL, "http://elsewhere/abc", "http://elsewhere/abc/info.json"),
    ],
)
def test_info_json_is_fetched_from_the_internal_host(settings, public_host, internal_host, identifier, expected_url):
    settings.IIIF_HOST = public_host
    settings.IIIF_INTERNAL_HOST = internal_host
    with patch("urllib.request.urlopen", return_value=_info_response(10, 20)) as mock_urlopen:
        assert resolve_image_dimensions(identifier) == (10, 20)
    mock_urlopen.assert_called_once_with(expected_url, timeout=5)

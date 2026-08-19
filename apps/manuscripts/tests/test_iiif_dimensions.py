"""Tests for IIIF image dimension resolution (retry + fallback logging)."""

import io
import json
import logging
from unittest.mock import patch

import pytest

from apps.manuscripts.iiif import (
    FALLBACK_IMAGE_DIMS,
    _fetch_info_dimensions,
    _internal_info_json_url,
    resolve_image_dimensions,
)


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
        caplog.at_level(logging.WARNING, logger="apps.manuscripts.iiif"),
    ):
        assert resolve_image_dimensions("http://sipi/unreachable") == FALLBACK_IMAGE_DIMS

    assert any("unreachable" in record.getMessage() for record in caplog.records)


def test_malformed_response_falls_back_without_retrying():
    with patch("urllib.request.urlopen", return_value=io.BytesIO(b"not json")) as mock_urlopen:
        assert resolve_image_dimensions("http://sipi/broken") == FALLBACK_IMAGE_DIMS
    # Malformed JSON can't be fixed by retrying, so only one attempt is made.
    assert mock_urlopen.call_count == 1


class TestInternalInfoJsonUrl:
    """`identifier` is built from the public IIIF_HOST for browsers; the
    server-to-server info.json fetch must instead resolve against
    IIIF_INTERNAL_HOST, which is unreachable-from-container `localhost` in a
    typical Docker Compose deployment."""

    def test_noop_when_internal_host_equals_public_host(self, settings):
        settings.IIIF_HOST = "http://localhost:8182"
        settings.IIIF_INTERNAL_HOST = "http://localhost:8182"
        assert _internal_info_json_url("http://localhost:8182/abc") == "http://localhost:8182/abc/info.json"

    def test_rewrites_the_host_when_identifier_matches_the_public_prefix(self, settings):
        settings.IIIF_HOST = "http://localhost:8182"
        settings.IIIF_INTERNAL_HOST = "http://image_server:1024"
        assert (
            _internal_info_json_url("http://localhost:8182/abc/def")
            == "http://image_server:1024/abc/def/info.json"
        )

    def test_tolerates_a_trailing_slash_on_either_host(self, settings):
        settings.IIIF_HOST = "http://localhost:8182/"
        settings.IIIF_INTERNAL_HOST = "http://image_server:1024/"
        assert (
            _internal_info_json_url("http://localhost:8182/abc") == "http://image_server:1024/abc/info.json"
        )

    def test_leaves_a_non_matching_identifier_unchanged(self, settings):
        """Defensive: an identifier that isn't under IIIF_HOST (unexpected,
        but shouldn't crash) is passed through rather than mis-rewritten."""
        settings.IIIF_HOST = "http://localhost:8182"
        settings.IIIF_INTERNAL_HOST = "http://image_server:1024"
        assert _internal_info_json_url("http://elsewhere/abc") == "http://elsewhere/abc/info.json"

    def test_fetch_info_dimensions_requests_the_rewritten_url(self, settings):
        settings.IIIF_HOST = "http://localhost:8182"
        settings.IIIF_INTERNAL_HOST = "http://image_server:1024"
        with patch("urllib.request.urlopen", return_value=_info_response(10, 20)) as mock_urlopen:
            assert _fetch_info_dimensions("http://localhost:8182/leaf-1") == (10, 20)
        mock_urlopen.assert_called_once_with("http://image_server:1024/leaf-1/info.json", timeout=5)

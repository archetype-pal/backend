"""`RequestIDMiddleware`: every response carries an `X-Request-ID`, minted or echoed."""

import pytest

from apps.common.middleware import REQUEST_ID_HEADER

pytestmark = pytest.mark.django_db


def test_each_request_without_an_id_gets_its_own(api_client):
    first = api_client.get("/api/v1/version/").headers[REQUEST_ID_HEADER]
    second = api_client.get("/api/v1/version/").headers[REQUEST_ID_HEADER]

    assert len(first) >= 8
    assert first != second


def test_an_incoming_id_is_echoed_back_truncated_to_128_chars(api_client):
    assert api_client.get("/api/v1/version/", HTTP_X_REQUEST_ID="abc-123").headers[REQUEST_ID_HEADER] == "abc-123"
    assert len(api_client.get("/api/v1/version/", HTTP_X_REQUEST_ID="x" * 1000).headers[REQUEST_ID_HEADER]) == 128

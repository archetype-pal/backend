"""Tests for apps.common.middleware.RequestIDMiddleware (P1.4)."""

import pytest

from apps.common.middleware import REQUEST_ID_HEADER


@pytest.mark.django_db
class TestRequestIDMiddleware:
    """Verify X-Request-ID minting/propagation contract."""

    def test_response_carries_minted_id_when_request_has_none(self, api_client):
        response = api_client.get("/api/v1/schema/")
        assert REQUEST_ID_HEADER in response.headers
        assert len(response.headers[REQUEST_ID_HEADER]) >= 8

    def test_response_echoes_incoming_request_id(self, api_client):
        incoming = "test-request-id-12345"
        response = api_client.get(
            "/api/v1/schema/",
            HTTP_X_REQUEST_ID=incoming,
        )
        assert response.headers[REQUEST_ID_HEADER] == incoming

    def test_excessively_long_incoming_id_is_truncated(self, api_client):
        long_id = "x" * 1000
        response = api_client.get(
            "/api/v1/schema/",
            HTTP_X_REQUEST_ID=long_id,
        )
        assert len(response.headers[REQUEST_ID_HEADER]) == 128

    def test_each_request_without_incoming_id_gets_a_unique_id(self, api_client):
        r1 = api_client.get("/api/v1/schema/")
        r2 = api_client.get("/api/v1/schema/")
        assert r1.headers[REQUEST_ID_HEADER] != r2.headers[REQUEST_ID_HEADER]

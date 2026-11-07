"""A throttled request answers in words, and keeps the header a client can act on."""

from rest_framework.exceptions import Throttled
from rest_framework.test import APIRequestFactory

from apps.common.exceptions import THROTTLED, drf_exception_handler


def test_a_throttled_request_is_worded_for_people():
    response = drf_exception_handler(Throttled(wait=3512), {"request": APIRequestFactory().get("/")})

    assert response.status_code == 429
    assert response.data == {"detail": THROTTLED, "code": "throttled"}
    assert response["Retry-After"] == "3512"

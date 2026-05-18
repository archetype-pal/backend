"""Shared request-scoped middleware."""

from collections.abc import Callable
import contextvars
import logging
import uuid

from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class RequestIdLogFilter(logging.Filter):
    """Attach the active request_id to every log record passing through a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


def get_request_id_filter() -> RequestIdLogFilter:
    """Factory referenced from Django LOGGING config (``filters[request_id]``)."""
    return RequestIdLogFilter()


class RequestIDMiddleware:
    """Mint or propagate X-Request-ID and expose it to logs (P1.4).

    Incoming header is trusted if present, capped to 128 chars to avoid log
    poisoning. A new id is minted otherwise. The id is set back on the response
    so callers can correlate across services.
    """

    MAX_HEADER_LENGTH = 128

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming[: self.MAX_HEADER_LENGTH] if incoming else uuid.uuid4().hex
        request.request_id = request_id
        token = _request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            _request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

"""Shared request-scoped middleware."""

from collections.abc import Callable
import logging
import uuid

from django.http import HttpRequest, HttpResponse

REQUEST_ID_HEADER = "X-Request-ID"


class _RequestIdLogFilter(logging.Filter):
    """Inject the current request_id into every log record on this thread."""

    request_id: str = "-"

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = self.request_id or "-"
        return True


_REQUEST_ID_FILTER = _RequestIdLogFilter()


def install_request_id_filter() -> None:
    """Attach the request-id filter to the root logger. Idempotent."""
    root = logging.getLogger()
    if _REQUEST_ID_FILTER not in root.filters:
        root.addFilter(_REQUEST_ID_FILTER)


class RequestIDMiddleware:
    """Mint or propagate X-Request-ID and expose it to logs (P1.4).

    Incoming header is trusted if present, capped to 128 chars to avoid log
    poisoning. A new id is minted otherwise. The id is set back on the response
    so callers can correlate across services.
    """

    MAX_HEADER_LENGTH = 128

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        install_request_id_filter()

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming[: self.MAX_HEADER_LENGTH] if incoming else uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        _REQUEST_ID_FILTER.request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            _REQUEST_ID_FILTER.request_id = "-"
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

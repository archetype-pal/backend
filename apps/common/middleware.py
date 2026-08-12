"""Shared request-scoped middleware."""

from collections.abc import Callable
import contextvars
import logging
import uuid

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.module_loading import import_string

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


class ResolveAuthenticatedUserMiddleware:
    """Best-effort DRF authentication ahead of the view.

    DRF only resolves ``request.user`` when something reads it on its own
    wrapped Request object. ``IsAuthenticatedOrReadOnly`` short-circuits on
    safe methods (``request.method in SAFE_METHODS or ...``) without ever
    touching ``request.user``, so a validly token-authenticated GET leaves
    the underlying Django request looking anonymous — which is what a
    mail_admins error-notification email would then attribute the error to.
    Running the configured DRF authenticators here, once, up front, means
    ``request.user`` reflects the real caller everywhere, not just on writes.

    Must sit after AuthenticationMiddleware in MIDDLEWARE: that middleware
    sets request.user to a lazily-resolved session user, and would overwrite
    our assignment if it ran afterwards.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response
        self.authenticator_classes = [
            import_string(path) for path in settings.REST_FRAMEWORK.get("DEFAULT_AUTHENTICATION_CLASSES", ())
        ]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        for authenticator_class in self.authenticator_classes:
            try:
                result = authenticator_class().authenticate(request)
            except Exception:
                # A malformed/expired credential, or an infra hiccup (e.g. DB
                # blip during the token lookup) — either way, not this
                # middleware's job to enforce. The view still authenticates
                # (and rejects) properly through DRF's own mechanism; if the
                # cause was a real outage, the view's own DB access will hit
                # it again and get logged/emailed there.
                continue
            if result is not None:
                request.user, request.auth = result
                break
        return self.get_response(request)

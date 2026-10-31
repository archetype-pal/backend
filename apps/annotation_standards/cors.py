"""Everything that makes the public IIIF / W3C endpoints readable from any origin.

`CorsMiddleware` only decorates origins in `CORS_ALLOWED_ORIGINS`; third-party
viewers (Mirador, UV) never are, so these endpoints answer their own preflight
and stamp a wildcard policy on every response.
"""

from functools import wraps

from django.http import HttpResponse

CORS_FALLBACK_HEADERS = "Accept, Content-Type, Range, If-Modified-Since, Cache-Control, X-Requested-With"


def apply_cors_headers(response, request) -> None:
    """Mark a response world-readable; the IIIF preflight middleware uses this too."""
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    response["Access-Control-Allow-Headers"] = (
        request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or CORS_FALLBACK_HEADERS
    )
    response["Access-Control-Max-Age"] = "86400"


def iiif_cors(view):
    """Mark IIIF responses world-readable; preflight is handled in middleware."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = HttpResponse(status=204) if request.method == "OPTIONS" else view(request, *args, **kwargs)
        apply_cors_headers(response, request)
        return response

    return wrapper


IIIF_PREFIX = "/api/v1/iiif/"


class IIIFCorsPreflightMiddleware:
    """Answer CORS preflight for the IIIF endpoints with a wildcard origin.

    Must precede CorsMiddleware, which claims every preflight in process_request
    and only decorates it for origins in CORS_ALLOWED_ORIGINS — third-party
    viewers never are. Scoped to IIIF_PREFIX so the management API keeps its
    strict allowlist.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(IIIF_PREFIX) and request.META.get("HTTP_ACCEPT", "").strip() == "":
            # An empty Accept means "no acceptable type" to DRF and 406s. Mirador 3's
            # request preprocessor sends one for any non-first-party host.
            request.META["HTTP_ACCEPT"] = "*/*"
            # DRF >=3.18 negotiates off request.headers, not request.META. `headers` is a
            # cached_property already populated by RequestIDMiddleware upstream, so drop
            # the stale snapshot and let it rebuild from the META we just corrected.
            request.__dict__.pop("headers", None)

        if (
            request.method == "OPTIONS"
            and "HTTP_ACCESS_CONTROL_REQUEST_METHOD" in request.META
            and request.path.startswith(IIIF_PREFIX)
        ):
            response = HttpResponse(status=204)
            apply_cors_headers(response, request)
            return response
        return self.get_response(request)

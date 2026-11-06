"""Everything that makes the public IIIF / W3C endpoints readable from any origin.

`CorsMiddleware` only decorates origins in `CORS_ALLOWED_ORIGINS`; third-party
viewers (Mirador, UV) never are, so one middleware answers their preflight and
stamps a wildcard policy on every response under the standards mounts.
"""

from django.http import HttpResponse

CORS_FALLBACK_HEADERS = "Accept, Content-Type, Range, If-Modified-Since, Cache-Control, X-Requested-With"

STANDARDS_PREFIXES = ("/api/v1/iiif/", "/api/v1/annotations-w3c/")


def apply_cors_headers(response, request) -> None:
    """Mark a response world-readable."""
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    response["Access-Control-Allow-Headers"] = (
        request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or CORS_FALLBACK_HEADERS
    )
    response["Access-Control-Max-Age"] = "86400"


class StandardsCorsMiddleware:
    """CORS for the IIIF and W3C endpoints: any origin may read them.

    Must precede CorsMiddleware, which claims every preflight in process_request
    and only decorates it for origins in CORS_ALLOWED_ORIGINS. Scoped to
    STANDARDS_PREFIXES so the rest of the API keeps its strict allowlist.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(STANDARDS_PREFIXES):
            return self.get_response(request)

        if request.META.get("HTTP_ACCEPT", "").strip() == "":
            # An empty Accept means "no acceptable type" to DRF and 406s. Mirador 3's
            # request preprocessor sends one for any non-first-party host.
            request.META["HTTP_ACCEPT"] = "*/*"
            # DRF >=3.18 negotiates off request.headers, not request.META. `headers` is a
            # cached_property already populated by RequestIDMiddleware upstream, so drop
            # the stale snapshot and let it rebuild from the META we just corrected.
            request.__dict__.pop("headers", None)

        response = HttpResponse(status=204) if request.method == "OPTIONS" else self.get_response(request)
        apply_cors_headers(response, request)
        return response

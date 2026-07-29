"""CORS preflight handling for the public IIIF endpoints."""

from django.http import HttpResponse

IIIF_PREFIX = "/api/v1/iiif/"

FALLBACK_ALLOW_HEADERS = "Accept, Content-Type, Range, If-Modified-Since, Cache-Control, X-Requested-With"


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
        if (
            request.method == "OPTIONS"
            and "HTTP_ACCESS_CONTROL_REQUEST_METHOD" in request.META
            and request.path.startswith(IIIF_PREFIX)
        ):
            response = HttpResponse(status=204)
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
            response["Access-Control-Allow-Headers"] = (
                request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or FALLBACK_ALLOW_HEADERS
            )
            response["Access-Control-Max-Age"] = "86400"
            return response
        return self.get_response(request)

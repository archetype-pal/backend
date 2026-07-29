"""CORS preflight handling for the public IIIF endpoints."""

from django.http import HttpResponse

IIIF_PREFIX = "/api/v1/iiif/"

# Used only when the browser sends no Access-Control-Request-Headers.
FALLBACK_ALLOW_HEADERS = "Accept, Content-Type, Range, If-Modified-Since, Cache-Control, X-Requested-With"


class IIIFCorsPreflightMiddleware:
    """Answer CORS preflight for the IIIF endpoints, ahead of CorsMiddleware.

    django-cors-headers short-circuits *every* preflight in process_request and
    then adds the CORS headers in process_response only when the Origin appears
    in CORS_ALLOWED_ORIGINS. A third-party IIIF viewer is by definition not in
    that allowlist, so its preflight came back 200 with no CORS headers at all
    and the browser failed the fetch before the GET was ever attempted — the
    viewer surfaces only an opaque "TypeError: Failed to fetch", with no status
    code to debug from. Observed against the Bodleian's hosted Mirador, which
    sends a non-safelisted request header and so triggers a preflight where
    projectmirador.org's build does not.

    This must sit BEFORE corsheaders.middleware.CorsMiddleware in MIDDLEWARE, or
    that middleware claims the preflight first and this never runs. It is scoped
    to IIIF_PREFIX so the credentialed management API keeps its strict origin
    allowlist — the alternative, CORS_ALLOW_ALL_ORIGINS, would open everything.

    Answering here also keeps preflight off the DRF throttle budget and away
    from the database.
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
            # Echo whatever the browser asked for: the response carries no
            # credentials and the data is public and read-only, so reflecting
            # the requested headers grants nothing a plain GET could not reach.
            response["Access-Control-Allow-Headers"] = (
                request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or FALLBACK_ALLOW_HEADERS
            )
            response["Access-Control-Max-Age"] = "86400"
            return response
        return self.get_response(request)

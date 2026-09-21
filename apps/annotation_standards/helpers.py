"""Shared plumbing for the IIIF Presentation and W3C Web Annotation views."""

from __future__ import annotations

from typing import cast

from rest_framework.request import Request

CORS_FALLBACK_HEADERS = "Accept, Content-Type, Range, If-Modified-Since, Cache-Control, X-Requested-With"


def base_url(request: Request) -> str:
    return f"{request.scheme}://{request.get_host()}"


def image_identifier(image) -> str | None:
    """The IIIF identifier for an ItemImage, or None when unresolvable."""
    try:
        return cast("str | None", image.image.iiif.identifier)
    except (AttributeError, TypeError, ValueError):  # fmt: skip
        return None


def apply_cors_headers(response, request) -> None:
    """Mark a response world-readable, mirroring the preflight in middleware.py."""
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    response["Access-Control-Allow-Headers"] = (
        request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or CORS_FALLBACK_HEADERS
    )
    response["Access-Control-Max-Age"] = "86400"

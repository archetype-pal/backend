"""IIIF Presentation 3.0 endpoints (public, read-only)."""

from functools import wraps

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText, ItemImage, ItemPart
from apps.manuscripts.services.tei import referenced_graph_ids

from .content_search import build_content_search
from .manifest import build_manifest

_IIIF = "application/ld+json"


class IIIFJSONRenderer(JSONRenderer):
    """DRF's JSONRenderer only advertises application/json, which 406s IIIF clients."""

    media_type = _IIIF
    format = "jsonld"


# JSON-LD leads so `Accept: */*` resolves to it; never negotiate to the browsable API.
_IIIF_RENDERERS = [IIIFJSONRenderer, JSONRenderer]

_CORS_FALLBACK_HEADERS = "Accept, Content-Type, Range, If-Modified-Since, Cache-Control, X-Requested-With"


def _base_url(request: Request) -> str:
    return f"{request.scheme}://{request.get_host()}"


def iiif_cors(view):
    """Mark IIIF responses world-readable; preflight is handled in middleware."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = view(request, *args, **kwargs)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        response["Access-Control-Allow-Headers"] = (
            request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS") or _CORS_FALLBACK_HEADERS
        )
        response["Access-Control-Max-Age"] = "86400"
        return response

    return wrapper


def _iiif_response(payload) -> Response:
    return Response(payload, content_type=_IIIF)


def _load_item_part_iiif_data(request: Request, item_part_id: int):
    """Shared loader for the manifest + content-search views.

    Returns (item_part, images, texts_by_image, graph_lookup), with the same
    public-visibility filter (anon sees Live/Reviewed texts only).
    """
    item_part = get_object_or_404(ItemPart, pk=item_part_id)
    images = list(ItemImage.objects.filter(item_part=item_part).order_by("locus", "id"))
    image_ids = [img.id for img in images]

    texts_qs = ImageText.objects.filter(item_image_id__in=image_ids).visible_to(request.user)

    texts_by_image: dict[int, list] = {}
    wanted: set[int] = set()
    for text in texts_qs:
        texts_by_image.setdefault(text.item_image_id, []).append(text)
        wanted |= referenced_graph_ids(text.content or "")

    graph_lookup = {g.id: g for g in Graph.objects.live().filter(id__in=wanted).select_related("item_image")}
    return item_part, images, texts_by_image, graph_lookup


@iiif_cors
@api_view(["GET"])
@permission_classes([])
@renderer_classes(_IIIF_RENDERERS)
def item_part_manifest(request: Request, item_part_id: int) -> Response:
    """A IIIF Presentation 3.0 Manifest for a manuscript part."""
    item_part, images, texts_by_image, graph_lookup = _load_item_part_iiif_data(request, item_part_id)
    manifest = build_manifest(
        item_part,
        images=images,
        texts_by_image=texts_by_image,
        graph_lookup=graph_lookup,
        base_url=_base_url(request),
    )
    return _iiif_response(manifest)


@iiif_cors
@api_view(["GET"])
@permission_classes([])
@renderer_classes(_IIIF_RENDERERS)
def item_part_search(request: Request, item_part_id: int) -> Response:
    """IIIF Content Search 2.0: regions whose linked transcription matches ?q."""
    item_part, images, texts_by_image, graph_lookup = _load_item_part_iiif_data(request, item_part_id)
    page = build_content_search(
        item_part,
        images=images,
        texts_by_image=texts_by_image,
        graph_lookup=graph_lookup,
        query=request.query_params.get("q", ""),
        base_url=_base_url(request),
    )
    return _iiif_response(page)

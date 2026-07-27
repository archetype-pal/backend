"""IIIF Presentation 3.0 endpoints (public, read-only)."""

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

# IIIF resources are machine-readable documents and must ALWAYS be served as
# JSON-LD, whatever the client asks for. Left to DRF's default renderer set, a
# request carrying a browser's `Accept: text/html,...` content-negotiates to the
# BrowsableAPIRenderer and returns an HTML page instead of the manifest — so a
# shared manifest link opened in a browser serves markup no viewer can read, and
# any client whose Accept header prefers HTML silently gets the wrong document.
# (It also 500s outright when staticfiles have not been collected, because the
# browsable template's {% static %} call raises under ManifestStaticFilesStorage.)
_IIIF_RENDERERS = [JSONRenderer]


def _base_url(request: Request) -> str:
    return f"{request.scheme}://{request.get_host()}"


def _iiif_response(payload) -> Response:
    """A public IIIF JSON-LD response.

    IIIF resources are meant to be consumable by any viewer on any origin
    (Mirador, UV, Annona), so these read-only endpoints answer with a wildcard
    CORS header rather than deferring to the site-wide CORS_ALLOWED_ORIGINS
    allowlist — that allowlist exists to gate the credentialed management API
    and would otherwise make every manifest unreadable to third-party viewers.
    """
    response = Response(payload, content_type=_IIIF)
    response["Access-Control-Allow-Origin"] = "*"
    return response


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

    graph_lookup = {g.id: g for g in Graph.objects.filter(id__in=wanted).select_related("item_image")}
    return item_part, images, texts_by_image, graph_lookup


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

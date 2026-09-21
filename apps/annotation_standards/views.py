"""Public, read-only endpoints publishing the corpus as IIIF Presentation 3.0
and W3C Web Annotation documents."""

from functools import wraps

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.manuscripts.iiif import resolve_image_dimensions
from apps.manuscripts.models import ImageText, ItemImage, ItemPart
from apps.manuscripts.services.tei import referenced_graph_ids

from .content_search import build_content_search
from .helpers import apply_cors_headers, base_url, image_identifier
from .manifest import build_manifest
from .w3c import W3C_CONTEXT, graph_to_w3c, imagetext_to_w3c

_JSONLD = "application/ld+json"


class IIIFJSONRenderer(JSONRenderer):
    """DRF's JSONRenderer only advertises application/json, which 406s IIIF clients."""

    media_type = _JSONLD
    format = "jsonld"


# JSON-LD leads so `Accept: */*` resolves to it; never negotiate to the browsable API.
_IIIF_RENDERERS = [IIIFJSONRenderer, JSONRenderer]


def iiif_cors(view):
    """Mark IIIF responses world-readable; preflight is handled in middleware."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = view(request, *args, **kwargs)
        apply_cors_headers(response, request)
        return response

    return wrapper


def _iiif_response(payload) -> Response:
    return Response(payload, content_type=_JSONLD)


def _image_height(image) -> int | None:
    """Resolve a graph/image's pixel height for the Y-flip; None if unknown."""
    identifier = image_identifier(image)
    if not identifier:
        return None
    return resolve_image_dimensions(identifier)[1]


def _visible_image_texts(request: Request):
    return ImageText.objects.select_related("item_image").visible_to(request.user)


def _load_item_part_iiif_data(request: Request, item_part_id: int):
    """Shared loader for the manifest + content-search views.

    Returns (item_part, images, texts_by_image, graph_lookup, graphs_by_image),
    with the same public-visibility filter (anon sees Live/Reviewed texts
    only). `graphs_by_image` holds every Graph for these images (all
    annotation types), keyed by item_image id — the manifest builder uses it
    to surface image/editorial annotations that aren't TEI-referenced text.
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

    graph_lookup = {
        g.id: g for g in Graph.objects.filter(id__in=wanted).select_related("item_image", "allograph__character")
    }

    graphs_by_image: dict[int, list] = {}
    for graph in Graph.objects.filter(item_image_id__in=image_ids).select_related("allograph__character"):
        graphs_by_image.setdefault(graph.item_image_id, []).append(graph)

    return item_part, images, texts_by_image, graph_lookup, graphs_by_image


@iiif_cors
@api_view(["GET"])
@permission_classes([])
@renderer_classes(_IIIF_RENDERERS)
def item_part_manifest(request: Request, item_part_id: int) -> Response:
    """A IIIF Presentation 3.0 Manifest for a manuscript part."""
    item_part, images, texts_by_image, graph_lookup, graphs_by_image = _load_item_part_iiif_data(request, item_part_id)
    manifest = build_manifest(
        item_part,
        images=images,
        texts_by_image=texts_by_image,
        graph_lookup=graph_lookup,
        graphs_by_image=graphs_by_image,
        base_url=base_url(request),
    )
    return _iiif_response(manifest)


@iiif_cors
@api_view(["GET"])
@permission_classes([])
@renderer_classes(_IIIF_RENDERERS)
def item_part_search(request: Request, item_part_id: int) -> Response:
    """IIIF Content Search 2.0: regions whose linked transcription matches ?q."""
    item_part, images, texts_by_image, graph_lookup, _graphs_by_image = _load_item_part_iiif_data(request, item_part_id)
    page = build_content_search(
        item_part,
        images=images,
        texts_by_image=texts_by_image,
        graph_lookup=graph_lookup,
        query=request.query_params.get("q", ""),
        base_url=base_url(request),
    )
    return _iiif_response(page)


@api_view(["GET"])
@permission_classes([])
def graph_annotation(request: Request, graph_id: int) -> Response:
    """A single image region as a W3C Web Annotation."""
    graph = get_object_or_404(Graph.objects.select_related("item_image", "allograph__character"), pk=graph_id)
    doc = graph_to_w3c(graph, base_url=base_url(request), image_height=_image_height(graph.item_image))
    return Response(doc, content_type=_JSONLD)


@api_view(["GET"])
@permission_classes([])
def image_text_page(request: Request, text_id: int) -> Response:
    """An ImageText's linked elements as a W3C AnnotationPage."""
    image_text = get_object_or_404(_visible_image_texts(request), pk=text_id)
    wanted = referenced_graph_ids(image_text.content or "")
    graph_lookup = {
        g.id: g for g in Graph.objects.filter(id__in=wanted).select_related("item_image", "allograph__character")
    }
    doc = imagetext_to_w3c(
        image_text,
        graph_lookup=graph_lookup,
        base_url=base_url(request),
        image_height=_image_height(image_text.item_image),
    )
    return Response(doc, content_type=_JSONLD)


@api_view(["GET"])
@permission_classes([])
def context(request: Request) -> Response:
    """Convenience pointer to the W3C Web Annotation context."""
    return Response({"@context": W3C_CONTEXT})

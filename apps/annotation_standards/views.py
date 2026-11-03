"""Public, read-only endpoints publishing the corpus as IIIF Presentation 3.0
and W3C Web Annotation documents."""

from collections.abc import Callable
from functools import wraps

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes, renderer_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText, ItemImage, ItemPart
from apps.manuscripts.services.iiif import item_image_identifier, resolve_image_dimensions
from apps.manuscripts.services.tei import referenced_graph_ids

from .content_search import build_content_search
from .manifest import build_manifest
from .w3c import W3C_CONTEXT, graph_to_w3c, imagetext_to_w3c

_JSONLD = "application/ld+json"


def base_url(request: Request) -> str:
    return f"{request.scheme}://{request.get_host()}"


class JSONLDRenderer(JSONRenderer):
    """DRF's JSONRenderer only advertises application/json, which 406s IIIF and W3C clients."""

    media_type = _JSONLD
    format = "jsonld"


def standards_view(view: Callable[..., dict]) -> Callable[..., Response]:
    """A public GET that serves the dict `view` returns as JSON-LD.

    JSON-LD leads the renderers so `Accept: */*` resolves to it, plain JSON is accepted, and the
    browsable API is never offered. The body is labelled JSON-LD whichever was asked for. CORS
    for these mounts is `cors.StandardsCorsMiddleware`'s.
    """

    @wraps(view)
    def respond(request: Request, *args, **kwargs) -> Response:
        return Response(view(request, *args, **kwargs), content_type=_JSONLD)

    endpoint: Callable[..., Response] = api_view(["GET"])(
        permission_classes([])(renderer_classes([JSONLDRenderer, JSONRenderer])(respond))
    )
    return endpoint


def _image_height(image) -> int | None:
    """Resolve a graph/image's pixel height for the Y-flip; None if unknown."""
    identifier = item_image_identifier(image)
    if not identifier:
        return None
    return resolve_image_dimensions(identifier)[1]


def _visible_graphs(request: Request):
    return Graph.objects.visible_to(request.user)


def _graph_lookup(request: Request, graph_ids: set[int]) -> dict[int, Graph]:
    """Visible graphs by id, with what the W3C/IIIF converters read joined in."""
    graphs = _visible_graphs(request).filter(id__in=graph_ids).select_related("item_image", "allograph__character")
    return {graph.id: graph for graph in graphs}


def _load_item_part_iiif_data(request: Request, item_part_id: int):
    """Shared loader for the manifest + content-search views.

    Returns (item_part, images, texts_by_image, graph_lookup, graphs_by_image),
    with the same public-visibility filters (anon sees Live/Reviewed texts
    only, and no editorial graphs). `graphs_by_image` holds every visible
    Graph for these images, keyed by item_image id — the manifest builder
    uses it to surface image/editorial annotations that aren't TEI-referenced
    text.
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

    graph_lookup = _graph_lookup(request, wanted)

    graphs_by_image: dict[int, list] = {}
    for graph in _visible_graphs(request).filter(item_image_id__in=image_ids).select_related("allograph__character"):
        graphs_by_image.setdefault(graph.item_image_id, []).append(graph)

    return item_part, images, texts_by_image, graph_lookup, graphs_by_image


@standards_view
def item_part_manifest(request: Request, item_part_id: int) -> dict:
    """A IIIF Presentation 3.0 Manifest for a manuscript part."""
    item_part, images, texts_by_image, graph_lookup, graphs_by_image = _load_item_part_iiif_data(request, item_part_id)
    return build_manifest(
        item_part,
        images=images,
        texts_by_image=texts_by_image,
        graph_lookup=graph_lookup,
        graphs_by_image=graphs_by_image,
        base_url=base_url(request),
    )


@standards_view
def item_part_search(request: Request, item_part_id: int) -> dict:
    """IIIF Content Search 2.0: regions whose linked transcription matches ?q."""
    item_part, images, texts_by_image, graph_lookup, _graphs_by_image = _load_item_part_iiif_data(request, item_part_id)
    return build_content_search(
        item_part,
        images=images,
        texts_by_image=texts_by_image,
        graph_lookup=graph_lookup,
        query=request.query_params.get("q", ""),
        base_url=base_url(request),
    )


@standards_view
def graph_annotation(request: Request, graph_id: int) -> dict:
    """A single image region as a W3C Web Annotation."""
    graph = get_object_or_404(
        _visible_graphs(request).select_related("item_image", "allograph__character"), pk=graph_id
    )
    return graph_to_w3c(graph, base_url=base_url(request), image_height=_image_height(graph.item_image))


@standards_view
def image_text_page(request: Request, text_id: int) -> dict:
    """An ImageText's linked elements as a W3C AnnotationPage."""
    texts = ImageText.objects.select_related("item_image").visible_to(request.user)
    image_text = get_object_or_404(texts, pk=text_id)
    return imagetext_to_w3c(
        image_text,
        graph_lookup=_graph_lookup(request, referenced_graph_ids(image_text.content or "")),
        base_url=base_url(request),
        image_height=_image_height(image_text.item_image),
    )


@standards_view
def context(request: Request) -> dict:
    """Convenience pointer to the W3C Web Annotation context."""
    return {"@context": W3C_CONTEXT}

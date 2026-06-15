"""W3C Web Annotation read endpoints (JSON-LD).

Public, read-only views over the canonical models. Visibility for text pages
mirrors the public ImageText rule (anon sees Live/Reviewed only).
"""

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.manuscripts.iiif import resolve_image_dimensions
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import referenced_graph_ids

from .converters import W3C_CONTEXT, graph_to_w3c, imagetext_to_w3c


def _image_height(image) -> int | None:
    """Resolve a graph/image's pixel height for the Y-flip; None if unknown."""
    try:
        identifier = image.image.iiif.identifier
    except AttributeError, TypeError, ValueError:
        return None
    if not identifier:
        return None
    return resolve_image_dimensions(identifier)[1]


_JSONLD = "application/ld+json"


def _base_url(request: Request) -> str:
    return f"{request.scheme}://{request.get_host()}"


def _visible_image_texts(request: Request):
    return ImageText.objects.select_related("item_image").visible_to(request.user)


@api_view(["GET"])
@permission_classes([])
def graph_annotation(request: Request, graph_id: int) -> Response:
    """A single image region as a W3C Web Annotation."""
    graph = get_object_or_404(Graph.objects.select_related("item_image"), pk=graph_id)
    doc = graph_to_w3c(graph, base_url=_base_url(request), image_height=_image_height(graph.item_image))
    return Response(doc, content_type=_JSONLD)


@api_view(["GET"])
@permission_classes([])
def image_text_page(request: Request, text_id: int) -> Response:
    """An ImageText's linked elements as a W3C AnnotationPage."""
    image_text = get_object_or_404(_visible_image_texts(request), pk=text_id)
    wanted = referenced_graph_ids(image_text.content or "")
    graph_lookup = {g.id: g for g in Graph.objects.filter(id__in=wanted).select_related("item_image")}
    doc = imagetext_to_w3c(
        image_text,
        graph_lookup=graph_lookup,
        base_url=_base_url(request),
        image_height=_image_height(image_text.item_image),
    )
    return Response(doc, content_type=_JSONLD)


@api_view(["GET"])
@permission_classes([])
def context(request: Request) -> Response:
    """Convenience pointer to the W3C Web Annotation context."""
    return Response({"@context": W3C_CONTEXT})

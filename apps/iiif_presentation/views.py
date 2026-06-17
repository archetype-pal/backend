"""IIIF Presentation 3.0 endpoints (public, read-only)."""

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText, ItemImage, ItemPart
from apps.manuscripts.services.tei import referenced_graph_ids

from .content_search import build_content_search
from .manifest import build_manifest

_IIIF = "application/ld+json"


def _base_url(request: Request) -> str:
    return f"{request.scheme}://{request.get_host()}"


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
    return Response(manifest, content_type=_IIIF)


@api_view(["GET"])
@permission_classes([])
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
    return Response(page, content_type=_IIIF)

"""IIIF Presentation 3.0 manifest builder (Track C2).

A derived view layer: builds a Manifest for an ItemPart with one Canvas per
ItemImage (painting annotation = the IIIF image) and, where the image has a
transcription/translation, a transcription AnnotationPage whose annotations are
anchored to image regions (the TEXT-typed Graphs the TEI references).

Canvas dimensions are resolved from the IIIF image info.json with a
per-process cache; resolution is injectable so it can be stubbed in tests and
falls back to a default when the image server is unreachable.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from apps.manuscripts.iiif import (
    FALLBACK_IMAGE_DIMS as _FALLBACK_DIMS,
    get_iiif_region_from_geojson,
    resolve_image_dimensions as resolve_dimensions,
)
from apps.manuscripts.services.tei import parse_graph_refs

from .content_search import search_service

PRESENTATION_CONTEXT = "http://iiif.io/api/presentation/3/context.json"


def _identifier(image) -> str | None:
    try:
        return cast("str | None", image.image.iiif.identifier)
    except AttributeError, TypeError, ValueError:
        return None


def _canvas(
    image,
    *,
    base_url: str,
    texts: list,
    graph_lookup: dict,
    width: int,
    height: int,
    identifier: str | None,
) -> dict[str, Any]:
    canvas_id = f"{base_url}/api/v1/iiif/canvas/{image.id}"

    canvas: dict[str, Any] = {
        "id": canvas_id,
        "type": "Canvas",
        "label": {"none": [image.locus or f"Image {image.id}"]},
        "height": height,
        "width": width,
    }
    if identifier:
        canvas["items"] = [
            {
                "id": f"{canvas_id}/page",
                "type": "AnnotationPage",
                "items": [
                    {
                        "id": f"{canvas_id}/painting",
                        "type": "Annotation",
                        "motivation": "painting",
                        "body": {
                            "id": f"{identifier}/full/max/0/default.jpg",
                            "type": "Image",
                            "format": "image/jpeg",
                            "height": height,
                            "width": width,
                            "service": [{"id": identifier, "type": "ImageService3", "profile": "level1"}],
                        },
                        "target": canvas_id,
                    }
                ],
            }
        ]

    supplement = _transcription_page(image, texts, graph_lookup, canvas_id, base_url, image_height=height)
    if supplement["items"]:
        canvas["annotations"] = [supplement]
    return canvas


def _transcription_page(image, texts, graph_lookup, canvas_id, base_url, *, image_height: int) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for text in texts:
        for ref in parse_graph_refs(text.content or ""):
            for gid in ref.graph_ids:
                graph = graph_lookup.get(gid)
                if graph is None:
                    continue
                try:
                    # image_height flips the legacy Y-up geometry into IIIF's
                    # top-left origin; without it every region is mislocated.
                    region = get_iiif_region_from_geojson(graph.annotation, image_height=image_height)
                except ValueError, TypeError, KeyError:
                    continue
                body: dict[str, Any] = {
                    "type": "TextualBody",
                    "value": ref.text,
                    "format": "text/plain",
                }
                if text.language:
                    body["language"] = text.language
                items.append(
                    {
                        "id": f"{base_url}/api/v1/iiif/canvas/{image.id}/text/{text.id}/{gid}",
                        "type": "Annotation",
                        "motivation": "supplementing",
                        "body": body,
                        "target": f"{canvas_id}#xywh={region}",
                    }
                )
    return {
        "id": f"{canvas_id}/transcription",
        "type": "AnnotationPage",
        "items": items,
    }


def build_manifest(
    item_part,
    *,
    images: list,
    texts_by_image: dict,
    graph_lookup: dict,
    base_url: str = "",
    dims: Callable[[str], tuple[int, int]] = resolve_dimensions,
) -> dict[str, Any]:
    label = item_part.display_label() if hasattr(item_part, "display_label") else str(item_part)

    # Resolve image dimensions concurrently so a cold cache over an N-image part
    # costs ~one timeout, not N serial timeouts (and never blocks per-canvas).
    identifiers = [_identifier(image) for image in images]
    distinct = sorted({i for i in identifiers if i})
    if distinct:
        with ThreadPoolExecutor(max_workers=min(8, len(distinct))) as pool:
            resolved = dict(zip(distinct, pool.map(dims, distinct), strict=True))
    else:
        resolved = {}

    canvases = []
    for image, identifier in zip(images, identifiers, strict=True):
        width, height = resolved.get(identifier, _FALLBACK_DIMS) if identifier else _FALLBACK_DIMS
        canvases.append(
            _canvas(
                image,
                base_url=base_url,
                texts=texts_by_image.get(image.id, []),
                graph_lookup=graph_lookup,
                width=width,
                height=height,
                identifier=identifier,
            )
        )
    return {
        "@context": PRESENTATION_CONTEXT,
        "id": f"{base_url}/api/v1/iiif/item-parts/{item_part.id}/manifest",
        "type": "Manifest",
        "label": {"none": [label]},
        "items": canvases,
        # Advertise search-within so IIIF clients (Mirador/UV) can query the
        # linked transcription regions of this manuscript part.
        "service": [search_service(item_part.id, base_url=base_url)],
    }

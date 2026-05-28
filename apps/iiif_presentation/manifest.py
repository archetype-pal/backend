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
from functools import lru_cache
import json
from typing import Any
import urllib.request

from apps.manuscripts.iiif import get_iiif_region_from_geojson
from apps.manuscripts.services.tei import parse_graph_refs

PRESENTATION_CONTEXT = "http://iiif.io/api/presentation/3/context.json"
_FALLBACK_DIMS = (1000, 1000)


@lru_cache(maxsize=4096)
def resolve_dimensions(identifier: str) -> tuple[int, int]:
    """(width, height) from the image's info.json; fallback on any failure."""
    try:
        with urllib.request.urlopen(f"{identifier}/info.json", timeout=4) as resp:
            info = json.loads(resp.read())
        return int(info["width"]), int(info["height"])
    except OSError, ValueError, KeyError, TypeError:
        return _FALLBACK_DIMS


def _identifier(image) -> str | None:
    try:
        return image.image.iiif.identifier
    except AttributeError, TypeError, ValueError:
        return None


def _canvas(
    image,
    *,
    base_url: str,
    texts: list,
    graph_lookup: dict,
    dims: Callable[[str], tuple[int, int]],
) -> dict[str, Any]:
    identifier = _identifier(image)
    width, height = dims(identifier) if identifier else _FALLBACK_DIMS
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

    supplement = _transcription_page(image, texts, graph_lookup, canvas_id, base_url)
    if supplement["items"]:
        canvas["annotations"] = [supplement]
    return canvas


def _transcription_page(image, texts, graph_lookup, canvas_id, base_url) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for text in texts:
        for ref in parse_graph_refs(text.content or ""):
            for gid in ref.graph_ids:
                graph = graph_lookup.get(gid)
                if graph is None:
                    continue
                try:
                    region = get_iiif_region_from_geojson(graph.annotation)
                except ValueError, TypeError, KeyError:
                    continue
                items.append(
                    {
                        "id": f"{base_url}/api/v1/iiif/canvas/{image.id}/text/{text.id}/{gid}",
                        "type": "Annotation",
                        "motivation": "supplementing",
                        "body": {
                            "type": "TextualBody",
                            "value": ref.text,
                            "format": "text/plain",
                            "language": text.language or None,
                        },
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
    canvases = [
        _canvas(
            image,
            base_url=base_url,
            texts=texts_by_image.get(image.id, []),
            graph_lookup=graph_lookup,
            dims=dims,
        )
        for image in images
    ]
    return {
        "@context": PRESENTATION_CONTEXT,
        "id": f"{base_url}/api/v1/iiif/item-parts/{item_part.id}/manifest",
        "type": "Manifest",
        "label": {"none": [label]},
        "items": canvases,
    }

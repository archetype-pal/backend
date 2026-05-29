"""Graph / ImageText → W3C Web Annotation (JSON-LD) converters.

Derived view layer over the canonical models (no new storage): an image region
is a `Graph`; a text↔region link is a `corresp`/`data-graph-id` reference from
the TEI to a TEXT-typed Graph. These converters serve that data as standard
W3C Web Annotations so external scholarly tools can consume it.

- `graph_to_w3c(graph)` — a region annotation (SVG + bbox selectors on the IIIF
  image), motivation by type.
- `imagetext_to_w3c(image_text)` — an AnnotationPage: one annotation per linked
  element, anchored in the text (TextQuoteSelector) and on the image region.
"""

from __future__ import annotations

import json
from typing import Any

from apps.manuscripts.services.tei import parse_graph_refs

W3C_CONTEXT = "http://www.w3.org/ns/anno.jsonld"

_MOTIVATION = {
    "image": "describing",  # a glyph / palaeographic instance
    "text": "identifying",  # a text element anchored to a region
    "editorial": "commenting",
}


def _geometry(graph_annotation: dict[str, Any]) -> list[list[float]] | None:
    try:
        geom = graph_annotation.get("geometry") or {}
        coords = geom.get("coordinates")
        if geom.get("type") == "Polygon" and coords:
            return coords[0]
    except AttributeError, TypeError, IndexError:
        return None
    return None


def _selectors(graph_annotation: dict[str, Any], image_height: int | None = None) -> list[dict[str, Any]]:
    """SVG polygon + bounding-box fragment selectors for a region's geometry.

    Stored geometry is Y-up (legacy bottom-left origin); IIIF/Media-Fragments
    target the Y-down image. When `image_height` is known, every point's Y is
    flipped (y_iiif = image_height - y_legacy) so the selectors are spatially
    correct; without it the raw coordinates are emitted (origin unknown).
    """
    ring = _geometry(graph_annotation)
    if not ring:
        return []
    pts = [(px, (image_height - py) if image_height is not None else py) for px, py in ring]
    xs = [px for px, _ in pts]
    ys = [py for _, py in pts]
    x, y = min(xs), min(ys)
    w, h = max(xs) - x, max(ys) - y
    points = " ".join(f"{round(px, 2)},{round(py, 2)}" for px, py in pts)
    return [
        {
            "type": "FragmentSelector",
            "conformsTo": "http://www.w3.org/TR/media-frags/",
            "value": f"xywh={round(x)},{round(y)},{round(w)},{round(h)}",
        },
        {
            "type": "SvgSelector",
            "value": f'<svg><polygon points="{points}" /></svg>',
        },
    ]


def _image_source(graph) -> str | None:
    image = getattr(graph, "item_image", None)
    if image is None:
        return None
    try:
        return image.image.iiif.identifier
    except AttributeError, TypeError, ValueError:
        return str(getattr(image, "image", "")) or None


def _linked_text(graph_annotation: dict[str, Any]) -> str | None:
    """The element text recorded by the H.5 reverse link, if any."""
    props = (graph_annotation or {}).get("properties") or {}
    elementid = props.get("elementid")
    if isinstance(elementid, dict):
        refs = elementid.get("refs") or []
        for ref in refs:
            if ref.get("text"):
                return ref["text"]
    return None


def graph_to_w3c(graph, *, base_url: str = "", image_height: int | None = None) -> dict[str, Any]:
    """Convert a single Graph (image/text/editorial) to a W3C Web Annotation."""
    annotation = graph.annotation or {}
    atype = graph.annotation_type or "image"
    source = _image_source(graph)
    target: dict[str, Any] = {"type": "Image"}
    if source:
        target["source"] = source
    selectors = _selectors(annotation, image_height)
    if selectors:
        target["selector"] = selectors

    body: list[dict[str, Any]] = []
    note = getattr(graph, "note", "") or ""
    if note:
        body.append({"type": "TextualBody", "value": note, "purpose": "commenting"})
    if atype == "text":
        text = _linked_text(annotation)
        if text:
            body.append({"type": "TextualBody", "value": text, "purpose": "transcribing"})
    if atype == "image" and getattr(graph, "allograph_id", None):
        body.append(
            {
                "type": "SpecificResource",
                "source": f"{base_url}/api/v1/symbols_structure/allographs/{graph.allograph_id}/",
                "purpose": "classifying",
            }
        )

    doc = {
        "@context": W3C_CONTEXT,
        "id": f"{base_url}/api/v1/annotations-w3c/graphs/{graph.id}/",
        "type": "Annotation",
        "motivation": _MOTIVATION.get(atype, "describing"),
        "target": target,
    }
    if body:
        doc["body"] = body
    return doc


def imagetext_to_w3c(
    image_text, *, graph_lookup=None, base_url: str = "", image_height: int | None = None
) -> dict[str, Any]:
    """Convert an ImageText to a W3C AnnotationPage.

    Each in-text graph reference becomes an annotation whose target combines a
    TextQuoteSelector (the element's text within this ImageText) with the image
    region of its linked Graph (when resolvable). `graph_lookup` maps graph id →
    Graph; if omitted, region geometry is omitted.
    """
    text_uri = f"{base_url}/api/v1/manuscripts/image-texts/{image_text.id}/"
    items: list[dict[str, Any]] = []

    for ref in parse_graph_refs(image_text.content or ""):
        for gid in ref.graph_ids:
            targets: list[dict[str, Any]] = [
                {
                    "source": text_uri,
                    "selector": {"type": "TextQuoteSelector", "exact": ref.text},
                }
            ]
            graph = graph_lookup.get(gid) if graph_lookup else None
            if graph is not None:
                region: dict[str, Any] = {"type": "Image"}
                source = _image_source(graph)
                if source:
                    region["source"] = source
                selectors = _selectors(graph.annotation or {}, image_height)
                if selectors:
                    region["selector"] = selectors
                targets.append(region)
            items.append(
                {
                    "id": f"{base_url}/api/v1/annotations-w3c/image-texts/{image_text.id}/{gid}/",
                    "type": "Annotation",
                    "motivation": "identifying",
                    "body": [
                        {
                            "type": "TextualBody",
                            "value": ref.type or ref.element,
                            "purpose": "tagging",
                        }
                    ],
                    "target": targets,
                }
            )

    return {
        "@context": W3C_CONTEXT,
        "id": f"{base_url}/api/v1/annotations-w3c/image-texts/{image_text.id}/",
        "type": "AnnotationPage",
        "items": items,
    }


def to_jsonld(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False)

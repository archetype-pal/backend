"""IIIF Content Search 2.0 over an ItemPart's linked transcription regions.

A search-within service attached to the manifest (see manifest.py): given a
query, it returns an AnnotationPage whose items target the image regions whose
linked transcription phrase matches — so a IIIF viewer can box the hit on the
page image.

Coverage note (deliberate, not a bug): matches are limited to transcription
phrases that an editor manually linked to an image region (a TEXT-typed Graph).
There are NO word-level coordinates for unlinked prose, so an arbitrary word
that is not part of a linked phrase has no region to return. Word-level search
would require HTR/ALTO word coordinates the project does not yet store.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from urllib.parse import quote

from apps.manuscripts.iiif import (
    FALLBACK_IMAGE_DIMS as _FALLBACK_DIMS,
    get_iiif_region_from_geojson,
    resolve_image_dimensions as resolve_dimensions,
)
from apps.manuscripts.services.tei import parse_graph_refs

SEARCH_CONTEXT = "http://iiif.io/api/search/2/context.json"


def _identifier(image) -> str | None:
    try:
        return cast("str | None", image.image.iiif.identifier)
    except AttributeError, TypeError, ValueError:
        return None


def search_service(item_part_id: int, *, base_url: str = "") -> dict[str, Any]:
    """The SearchService2 descriptor a manifest advertises so clients find search."""
    return {
        "id": f"{base_url}/api/v1/iiif/item-parts/{item_part_id}/search",
        "type": "SearchService2",
    }


def build_content_search(
    item_part,
    *,
    images: list,
    texts_by_image: dict,
    graph_lookup: dict,
    query: str,
    base_url: str = "",
    dims: Callable[[str], tuple[int, int]] = resolve_dimensions,
) -> dict[str, Any]:
    normalized = (query or "").strip()
    page_id = f"{base_url}/api/v1/iiif/item-parts/{item_part.id}/search?q={quote(normalized)}"
    empty = {"@context": SEARCH_CONTEXT, "id": page_id, "type": "AnnotationPage", "items": []}
    if not normalized:
        return empty
    needle = normalized.lower()

    # Resolve image dimensions concurrently (cached) — only `height` is needed,
    # to flip the legacy Y-up geometry into IIIF's top-left origin.
    identifiers = [_identifier(image) for image in images]
    distinct = sorted({i for i in identifiers if i})
    if distinct:
        with ThreadPoolExecutor(max_workers=min(8, len(distinct))) as pool:
            resolved = dict(zip(distinct, pool.map(dims, distinct), strict=True))
    else:
        resolved = {}

    items: list[dict[str, Any]] = []
    for image, identifier in zip(images, identifiers, strict=True):
        dims_tuple = resolved.get(identifier, _FALLBACK_DIMS) if identifier else _FALLBACK_DIMS
        height = dims_tuple[1]
        canvas_id = f"{base_url}/api/v1/iiif/canvas/{image.id}"
        for text in texts_by_image.get(image.id, []):
            for ref in parse_graph_refs(text.content or ""):
                phrase = (ref.text or "").strip()
                if not phrase or needle not in phrase.lower():
                    continue
                for gid in ref.graph_ids:
                    graph = graph_lookup.get(gid)
                    if graph is None:
                        continue
                    try:
                        region = get_iiif_region_from_geojson(graph.annotation, image_height=height)
                    except ValueError, TypeError, KeyError:
                        continue
                    body: dict[str, Any] = {"type": "TextualBody", "value": phrase, "format": "text/plain"}
                    if text.language:
                        body["language"] = text.language
                    items.append(
                        {
                            "id": f"{base_url}/api/v1/iiif/canvas/{image.id}/search/{text.id}/{gid}",
                            "type": "Annotation",
                            "motivation": "highlighting",
                            "body": body,
                            "target": f"{canvas_id}#xywh={region}",
                        }
                    )

    return {"@context": SEARCH_CONTEXT, "id": page_id, "type": "AnnotationPage", "items": items}

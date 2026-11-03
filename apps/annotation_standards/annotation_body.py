"""Shared Graph → annotation-body mapping.

Derived view logic over `Graph` (no new storage), shared by the W3C converter
(`w3c.graph_to_w3c`) and the IIIF Presentation manifest builder (`manifest`)
so both surface the same annotation content and motivation.
"""

from __future__ import annotations

from typing import Any

from apps.annotations.models import Graph

ANNOTATION_MOTIVATIONS = {
    Graph.AnnotationType.IMAGE: "describing",  # a glyph / palaeographic instance
    Graph.AnnotationType.TEXT: "identifying",  # a text element anchored to a region
    Graph.AnnotationType.EDITORIAL: "commenting",
}


def _allograph_label(graph) -> str | None:
    """'<allograph name> (<character name>)', or just the allograph name if
    its character is somehow unset. Callers should `select_related
    ("allograph__character")` — this reads both without re-querying."""
    allograph = getattr(graph, "allograph", None)
    if allograph is None:
        return None
    character = getattr(allograph, "character", None)
    return f"{allograph.name} ({character.name})" if character else allograph.name


def annotation_body_items(graph, *, base_url: str = "", include_creation_date: bool = False) -> list[dict[str, Any]]:
    """Body items for a Graph's annotation: a note (any type), optionally the
    graph's creation date, and — for image-type graphs — the allograph's name
    and character plus a classifying link to the allograph resource.

    A text region's passage is not repeated here: the text's TEI is the only
    record of which passage links to which region, and it carries the text's
    publication status, which a copy on the region would not."""
    atype = graph.annotation_type or Graph.AnnotationType.IMAGE
    body: list[dict[str, Any]] = []
    note = getattr(graph, "note", "") or ""
    if note:
        body.append({"type": "TextualBody", "value": note, "purpose": "commenting"})
    created = getattr(graph, "created", None)
    if include_creation_date and created:
        body.append({"type": "TextualBody", "value": created.date().isoformat(), "purpose": "describing"})
    if atype == Graph.AnnotationType.IMAGE and getattr(graph, "allograph_id", None):
        label = _allograph_label(graph)
        if label:
            body.append({"type": "TextualBody", "value": label, "purpose": "classifying"})
        body.append(
            {
                "type": "SpecificResource",
                "source": f"{base_url}/api/v1/symbols_structure/allographs/{graph.allograph_id}/",
                "purpose": "classifying",
            }
        )
    return body

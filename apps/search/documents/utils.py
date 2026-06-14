"""Shared helpers for document builders."""

import json

from apps.annotations.models import Graph


def get_attr(obj, path: str):
    """Follow relation path (e.g. ``item_part__current_item__shelfmark``) and return value or None."""
    for part in path.split("__"):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return str(obj) if obj is not None else None


def drop_none(d: dict, *, keep: set[str] | None = None) -> dict:
    """Return a copy with None values removed (Meilisearch-friendly).

    Keys listed in *keep* are preserved even when their value is None.
    """
    if keep:
        return {k: v for k, v in d.items() if v is not None or k in keep}
    return {k: v for k, v in d.items() if v is not None}


def unique_preserve_order(values: list[str]) -> list[str]:
    """Deduplicate a list while preserving insertion order."""
    seen = set()
    unique_values = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values


def annotation_coordinates_map(entries: list[dict]) -> dict[int, str]:
    """Map each entry's ``annotation_id`` to its Graph coordinates (JSON or str).

    *entries* are extracted clause/person/place dicts. Entries without an
    ``annotation_id`` are skipped, as are graphs that have no stored annotation.
    """
    annotation_ids = {annotation_id for entry in entries if (annotation_id := entry.get("annotation_id")) is not None}
    if not annotation_ids:
        return {}

    coordinates_by_id = {}
    graphs = Graph.objects.filter(id__in=annotation_ids)
    if hasattr(graphs, "only"):
        graphs = graphs.only("id", "annotation")
    for graph in graphs:
        if graph.annotation is None:
            continue
        if isinstance(graph.annotation, dict):
            coordinates_by_id[graph.id] = json.dumps(graph.annotation)
        else:
            coordinates_by_id[graph.id] = str(graph.annotation)
    return coordinates_by_id

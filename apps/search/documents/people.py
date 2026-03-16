"""Document builder for people index.

Like the clauses builder, this returns a **list** of dicts -- one Meilisearch
document per person mention found inside the ``ImageText.content`` HTML via
``<span data-dpt="person" ...>`` markup.
"""

import json

from apps.annotations.models import Graph
from apps.search.documents.dpt_parser import extract_people_detailed


def build_person_documents(obj) -> list[dict]:
    """Build search documents from an ImageText instance.

    Each ``<span data-dpt="person" ...>`` in the content produces one
    document.  Returns ``[]`` if the content contains no person markup.
    """
    if not obj.content:
        return []

    people = extract_people_detailed(obj.content)
    if not people:
        return []
    annotation_coordinates = _get_annotation_coordinates_map(people)

    # Pre-fetch shared metadata once (same traversal as texts/clauses builders)
    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    historical_item = getattr(item_part, "historical_item", None) if item_part else None

    shared = {
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "text_type": obj.type,
        "repository_city": _get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "repository_name": _get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "shelfmark": _get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "date": None,
        "date_min": None,
        "date_max": None,
        "catalogue_numbers": historical_item.get_catalogue_numbers_display() if historical_item else "",
        "locus": item_image.locus if item_image else "",
        "type": _get_attr(obj, "item_image__item_part__historical_item__type"),
        "status": obj.status,
        "thumbnail_iiif": item_image.image.iiif.info if item_image else None,
    }

    if historical_item and historical_item.date:
        shared["date"] = historical_item.date.date
        shared["date_min"] = historical_item.date.min_weight
        shared["date_max"] = historical_item.date.max_weight

    documents = []
    for idx, person in enumerate(people):
        annotation_id = person.get("annotation_id")
        doc = {
            "id": f"{obj.id}_p{idx}",
            "name": person["name"],
            "person_type": person["type"],
            "ref": person["ref"],
            "annotation_id": annotation_id,
            "annotation_coordinates": annotation_coordinates.get(annotation_id),
            **shared,
        }
        cleaned_doc = _drop_none(doc)
        if "annotation_id" not in cleaned_doc:
            cleaned_doc["annotation_id"] = None
        if "annotation_coordinates" not in cleaned_doc:
            cleaned_doc["annotation_coordinates"] = None
        documents.append(cleaned_doc)

    return documents


def _get_attr(obj, path: str):
    """Follow relation path and return value or None."""
    for part in path.split("__"):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return str(obj) if obj is not None else None


def _drop_none(d: dict) -> dict:
    """Return a copy with None values removed (Meilisearch-friendly)."""
    return {k: v for k, v in d.items() if v is not None}


def _get_annotation_coordinates_map(people: list[dict]) -> dict[int, str]:
    annotation_ids = {annotation_id for person in people if (annotation_id := person.get("annotation_id")) is not None}
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

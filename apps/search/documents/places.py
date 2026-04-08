"""Document builder for places index.

Like the clauses builder, this returns a **list** of dicts -- one Meilisearch
document per place mention found inside the ``ImageText.content`` HTML via
``<span data-dpt="place" ...>`` markup.
"""

import json

from apps.annotations.models import Graph
from apps.search.documents.dpt_parser import extract_places_detailed
from apps.search.documents.utils import drop_none, get_attr


def build_place_documents(obj) -> list[dict]:
    """Build search documents from an ImageText instance.

    Each ``<span data-dpt="place" ...>`` in the content produces one
    document.  Returns ``[]`` if the content contains no place markup.
    """
    if not obj.content:
        return []

    places = extract_places_detailed(obj.content)
    if not places:
        return []
    annotation_coordinates = _get_annotation_coordinates_map(places)

    # Pre-fetch shared metadata once (same traversal as texts/clauses builders)
    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    historical_item = getattr(item_part, "historical_item", None) if item_part else None

    shared = {
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "text_type": obj.type,
        "repository_city": get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "repository_name": get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "shelfmark": get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "date": None,
        "date_min": None,
        "date_max": None,
        "catalogue_numbers": historical_item.get_catalogue_numbers_display() if historical_item else "",
        "locus": item_image.locus if item_image else "",
        "type": get_attr(obj, "item_image__item_part__historical_item__type"),
        "status": obj.status,
        "thumbnail_iiif": item_image.image.iiif.info if item_image else None,
    }

    if historical_item and historical_item.date:
        shared["date"] = historical_item.date.date
        shared["date_min"] = historical_item.date.min_weight
        shared["date_max"] = historical_item.date.max_weight

    documents = []
    for idx, place in enumerate(places):
        raw_annotation_id = place.get("annotation_id")
        annotation_id = raw_annotation_id if isinstance(raw_annotation_id, int) else None
        doc = {
            "id": f"{obj.id}_l{idx}",
            "name": place["name"],
            "place_type": place["type"],
            "ref": place["ref"],
            "annotation_id": annotation_id,
            "annotation_coordinates": annotation_coordinates.get(annotation_id) if annotation_id is not None else None,
            **shared,
        }
        documents.append(drop_none(doc, keep={"annotation_id", "annotation_coordinates"}))

    return documents



def _get_annotation_coordinates_map(places: list[dict]) -> dict[int, str]:
    annotation_ids = {annotation_id for place in places if (annotation_id := place.get("annotation_id")) is not None}
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

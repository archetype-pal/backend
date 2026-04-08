"""Document builder for texts index."""

import json
import re

from apps.annotations.models import Graph
from apps.search.documents.dpt_parser import extract_all
from apps.search.documents.utils import drop_none, get_attr


def build_text_document(obj) -> dict:
    """Build a search document from an ImageText instance."""
    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    historical_item = getattr(item_part, "historical_item", None) if item_part else None

    doc = {
        "id": obj.id,
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "repository_city": get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "repository_name": get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "shelfmark": get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "text_type": obj.type,
        "date": None,
        "date_min": None,
        "date_max": None,
        "content": _strip_html_for_search(obj.content) if obj.content else "",
        "locus": item_image.locus if item_image else "",
        "catalogue_numbers": historical_item.get_catalogue_numbers_display() if historical_item else "",
        "type": get_attr(obj, "item_image__item_part__historical_item__type"),
        "status": obj.status,
        "language": obj.language,
        "thumbnail_iiif": item_image.image.iiif.info if item_image else None,
    }

    if historical_item and historical_item.date:
        doc["date"] = historical_item.date.date
        doc["date_min"] = historical_item.date.min_weight
        doc["date_max"] = historical_item.date.max_weight

    # Extract places/people and an optional annotation id from data-dpt markup.
    if obj.content:
        extracted = extract_all(obj.content)
        doc["places"] = list(dict.fromkeys(place["name"] for place in extracted["places"]))
        doc["people"] = list(dict.fromkeys(person["name"] for person in extracted["people"]))
        doc["annotation_id"] = _first_annotation_id(extracted)
        doc["annotation_coordinates"] = _get_annotation_coordinates(doc["annotation_id"])
    else:
        doc["places"] = []
        doc["people"] = []
        doc["annotation_id"] = None
        doc["annotation_coordinates"] = None

    return drop_none(doc, keep={"annotation_id", "annotation_coordinates"})


def _strip_html_for_search(html_content: str) -> str:
    """Strip HTML/XML tags from content for plain-text search indexing.

    Mirrors the legacy ``get_plain_text_from_xmltext`` behaviour: removes all
    markup, collapses whitespace, and returns clean searchable text.
    """
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", html_content)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text



def _first_annotation_id(extracted: dict) -> int | None:
    for group in ("clauses", "places", "people"):
        for entry in extracted.get(group, []):
            annotation_id = entry.get("annotation_id")
            if isinstance(annotation_id, int):
                return annotation_id
    return None


def _get_annotation_coordinates(annotation_id: int | None) -> str | None:
    if annotation_id is None:
        return None
    try:
        annotation = Graph.objects.only("annotation").get(id=annotation_id).annotation
    except Graph.DoesNotExist:
        return None
    if annotation is None:
        return None
    if isinstance(annotation, dict):
        return json.dumps(annotation)
    return str(annotation)

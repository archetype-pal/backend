"""Document builder for texts index."""

import re

from apps.search.documents.dpt_parser import extract_people, extract_places


def build_text_document(obj) -> dict:
    """Build a search document from an ImageText instance."""
    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    historical_item = getattr(item_part, "historical_item", None) if item_part else None

    doc = {
        "id": obj.id,
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "repository_city": _get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "repository_name": _get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "shelfmark": _get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "text_type": obj.type,
        "date": None,
        "date_min": None,
        "date_max": None,
        "content": _strip_html_for_search(obj.content) if obj.content else "",
        "locus": item_image.locus if item_image else "",
        "catalogue_numbers": historical_item.get_catalogue_numbers_display() if historical_item else "",
        "type": _get_attr(obj, "item_image__item_part__historical_item__type"),
        "status": obj.status,
        "language": obj.language,
        "thumbnail_iiif": item_image.image.iiif.info if item_image else None,
    }

    if historical_item and historical_item.date:
        doc["date"] = historical_item.date.date
        doc["date_min"] = historical_item.date.min_weight
        doc["date_max"] = historical_item.date.max_weight

    # Extract places and people from data-dpt markup in the HTML content.
    if obj.content:
        doc["places"] = extract_places(obj.content)
        doc["people"] = extract_people(obj.content)
    else:
        doc["places"] = []
        doc["people"] = []

    return _drop_none(doc)


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

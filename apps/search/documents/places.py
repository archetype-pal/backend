"""Document builder for places index.

Like the clauses builder, this returns a **list** of dicts -- one Meilisearch
document per place mention found inside the ``ImageText.content`` HTML via
``<span data-dpt="place" ...>`` markup.
"""

from apps.search.documents.dpt_parser import extract_places_detailed


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
    for idx, place in enumerate(places):
        doc = {
            "id": f"{obj.id}_l{idx}",
            "name": place["name"],
            "place_type": place["type"],
            "ref": place["ref"],
            **shared,
        }
        documents.append(_drop_none(doc))

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

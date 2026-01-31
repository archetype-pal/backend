"""Document builder for hands index."""


def build_hand_document(obj) -> dict:
    """Build a search document from a Hand instance."""
    catalogue_numbers = [str(cn) for cn in obj.item_part.historical_item.catalogue_numbers.all()]
    date_str = obj.date.date if obj.date else None
    doc = {
        "id": obj.id,
        "name": obj.name,
        "place": obj.place or "",
        "description": obj.description or "",
        "repository_name": _get_attr(obj, "item_part__current_item__repository__name"),
        "repository_city": _get_attr(obj, "item_part__current_item__repository__place"),
        "shelfmark": _get_attr(obj, "item_part__current_item__shelfmark"),
        "catalogue_numbers": catalogue_numbers,
        "date": date_str,
    }
    return _drop_none(doc)


def _get_attr(obj, path: str):
    """Follow relation path and return value or None."""
    for part in path.split("__"):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return str(obj) if obj is not None else None


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}

"""Document builder for hands index."""

from apps.search.documents.utils import drop_none, get_attr


def build_hand_document(obj) -> dict:
    """Build a search document from a Hand instance."""
    catalogue_numbers = [str(cn) for cn in obj.item_part.historical_item.catalogue_numbers.all()]
    date_str = obj.date.date if obj.date else None
    doc = {
        "id": obj.id,
        "name": obj.name,
        "place": obj.place or "",
        "description": obj.description or "",
        "repository_name": get_attr(obj, "item_part__current_item__repository__name"),
        "repository_city": get_attr(obj, "item_part__current_item__repository__place"),
        "shelfmark": get_attr(obj, "item_part__current_item__shelfmark"),
        "catalogue_numbers": catalogue_numbers,
        "date": date_str,
    }
    return drop_none(doc)

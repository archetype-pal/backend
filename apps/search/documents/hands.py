"""Document builder for hands index."""

from apps.search.documents.utils import drop_none, get_attr


def build_hand_document(obj) -> dict:
    """Build a search document from a Hand instance."""
    catalogue_numbers = [str(cn) for cn in obj.item_part.historical_item.catalogue_numbers.all()]
    date_str = obj.date.date if obj.date else None
    place_str = obj.place.name if obj.place else None
    # Hand.description is now zero-or-more HandDescription rows (with an
    # optional source each) rather than one free-text field — join their
    # content so full-text search still covers all of them.
    description_str = " ".join(d.content for d in obj.descriptions.all() if d.content)
    doc = {
        "id": obj.id,
        "name": obj.name,
        "place": place_str or "",
        "description": description_str or "",
        "repository_name": get_attr(obj, "item_part__current_item__repository__name"),
        "repository_city": get_attr(obj, "item_part__current_item__repository__place"),
        "shelfmark": get_attr(obj, "item_part__current_item__shelfmark"),
        "catalogue_numbers": catalogue_numbers,
        "date": date_str,
    }
    return drop_none(doc)

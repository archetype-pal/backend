from apps.search.documents.utils import drop_none, get_attr, strip_html_for_search


def build_hand_document(obj) -> dict:
    catalogue_numbers = [str(cn) for cn in obj.item_part.historical_item.catalogue_numbers.all()]
    date_str = obj.date.date if obj.date else None
    place_str = obj.place.name if obj.place else None
    # Hand.description is now zero-or-more HandDescription rows (with an
    # optional source each) rather than one free-text field — join their
    # content so full-text search still covers all of them. Content is rich
    # text, so strip the markup or Meilisearch indexes "<p>word</p>" as one token.
    description_str = " ".join(strip_html_for_search(d.content) for d in obj.descriptions.all() if d.content)
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

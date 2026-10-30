from apps.search.documents.utils import date_fields, drop_none, manuscript_context, strip_html_for_search


def build_hand_document(obj) -> dict:
    catalogue_numbers = [str(cn) for cn in obj.item_part.historical_item.catalogue_numbers.all()]
    place_str = obj.place.name if obj.place else None
    description_str = " ".join(strip_html_for_search(d.content) for d in obj.descriptions.all() if d.content)
    context = manuscript_context(obj.item_part)
    doc = {
        "id": obj.id,
        "name": obj.name,
        "place": place_str or "",
        "description": description_str or "",
        "repository_name": context["repository_name"],
        "repository_city": context["repository_city"],
        "shelfmark": context["shelfmark"],
        "shelfmark_sort": context["shelfmark_sort"],
        "catalogue_numbers": catalogue_numbers,
        # A hand document carries its own date, not its manuscript's.
        **date_fields(obj.date),
    }
    return drop_none(doc)

from apps.search.documents.utils import (
    catalogue_numbers,
    date_fields,
    drop_none,
    manuscript_context,
    strip_html_for_search,
)


def build_hand_document(obj) -> dict:
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
        "catalogue_numbers": catalogue_numbers(obj.item_part.historical_item),
        # `date` is the hand's own date, not its manuscript's.
        **date_fields(obj.date),
        **date_fields(getattr(obj.item_part.historical_item, "date", None), prefix="manuscript_date"),
    }
    return drop_none(doc)

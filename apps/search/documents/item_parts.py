import html

from apps.common.text import collapse_whitespace
from apps.search.documents.msdesc_parser import extract_msdesc_facets
from apps.search.documents.utils import (
    catalogue_numbers,
    display_label,
    drop_none,
    get_attr,
    manuscript_context,
    strip_html_for_search,
)


def build_item_part_document(obj) -> dict:
    images = obj.images.all()
    images_count = len(images)
    descriptions, description_source = _descriptions(obj.historical_item)
    doc = {
        "id": obj.id,
        "display_label": display_label(obj),
        **manuscript_context(obj),
        "catalogue_numbers": catalogue_numbers(obj.historical_item),
        "format": get_attr(obj, "historical_item__format__name"),
        "number_of_images": images_count,
        "image_availability": "With images" if images_count > 0 else "Without images",
        "first_image_iiif": _first_image_iiif(images),
        "description": descriptions or None,
        "description_source": description_source,
    }
    facets = _published_msdesc_facets(obj)
    origin_places = [origin.place.name for origin in obj.historical_item.origins.all()]
    if origin_places:
        # `Place` names are unique ignoring case, so spellings of one place are one value; the first wins.
        by_name: dict[str, str] = {}
        for name in [*facets.get("origin_place", []), *origin_places]:
            by_name.setdefault(name.casefold(), name)
        facets["origin_place"] = list(by_name.values())
    doc.update(facets)
    return drop_none(doc)


def _published_msdesc_facets(obj) -> dict[str, list[str]]:
    """Facets parsed from this part's **published** msDesc fragments only.

    The public facet rail is anonymous-facing, so an unpublished script or
    material attribution must never become a facet value — that would leak draft
    cataloguing past the same `is_published` gate the public API and the `.tei`
    export enforce. Filtered in Python rather than with `.filter()` so the
    registry's ``msdesc_areas`` prefetch stays warm (a queryset filter would
    re-query once per row during a reindex).
    """
    areas = getattr(obj, "msdesc_areas", None)
    if areas is None:
        return {}
    return extract_msdesc_facets(area.content for area in areas.all() if area.is_published)


def _descriptions(historical_item) -> tuple[list[str], str | None]:
    described = [
        (description.source.label, text)
        for description in historical_item.descriptions.all()
        if (text := collapse_whitespace(html.unescape(strip_html_for_search(description.content))))
    ]
    return [text for _, text in described], described[0][0] if described else None


def _first_image_iiif(images) -> str | None:
    for image in images:
        try:
            info: str = image.image.iiif.info
            return info
        except AttributeError, ValueError:
            continue
    return None

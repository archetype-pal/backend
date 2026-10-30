from apps.search.documents.msdesc_parser import extract_msdesc_facets
from apps.search.documents.utils import catalogue_numbers, display_label, drop_none, get_attr, manuscript_context


def build_item_part_document(obj) -> dict:
    images = obj.images.all()
    images_count = len(images)
    doc = {
        "id": obj.id,
        "display_label": display_label(obj),
        **manuscript_context(obj),
        "catalogue_numbers": catalogue_numbers(obj.historical_item),
        "format": get_attr(obj, "historical_item__format__name"),
        "number_of_images": images_count,
        "image_availability": "With images" if images_count > 0 else "Without images",
        "first_image_iiif": _first_image_iiif(images),
    }
    doc.update(_published_msdesc_facets(obj))
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


def _first_image_iiif(images) -> str | None:
    for image in images:
        try:
            info: str = image.image.iiif.info
            return info
        except AttributeError:
            continue
        except ValueError:
            continue
    return None

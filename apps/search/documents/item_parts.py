"""Document builder for item_parts index."""

from apps.search.documents.utils import drop_none, get_attr


def build_item_part_document(obj) -> dict:
    """Build a search document from an ItemPart instance."""
    images = obj.images.all()
    images_count = len(images)
    doc = {
        "id": obj.id,
        "display_label": _display_label(obj),
        "repository_name": get_attr(obj, "current_item__repository__name"),
        "repository_city": get_attr(obj, "current_item__repository__place"),
        "shelfmark": get_attr(obj, "current_item__shelfmark"),
        "catalogue_numbers": obj.historical_item.get_catalogue_numbers_display() if obj.historical_item else "",
        "date": None,
        "date_min": None,
        "date_max": None,
        "type": get_attr(obj, "historical_item__type"),
        "format": get_attr(obj, "historical_item__format__name"),
        "number_of_images": images_count,
        "image_availability": "With images" if images_count > 0 else "Without images",
        "first_image_iiif": _first_image_iiif(images),
    }
    if obj.historical_item and obj.historical_item.date:
        doc["date"] = obj.historical_item.date.date
        doc["date_min"] = obj.historical_item.date.min_weight
        doc["date_max"] = obj.historical_item.date.max_weight
    return drop_none(doc)


def _first_image_iiif(images) -> str | None:
    """Return the IIIF info URL of the first image, or None."""
    for image in images:
        try:
            info: str = image.image.iiif.info
            return info
        except AttributeError:
            continue
        except ValueError:
            continue
    return None


def _display_label(obj) -> str | None:
    value = getattr(obj, "display_label", None)
    if callable(value):
        value = value()
    if value is None:
        return None
    return str(value).strip() or None

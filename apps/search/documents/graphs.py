"""Document builder for graphs index."""

import json

from apps.search.documents.utils import drop_none, get_attr, unique_preserve_order


def build_graph_document(obj) -> dict:
    """Build a search document from a Graph instance."""
    components = [c.name for c in obj.components.all()]
    features = []
    component_features = []
    graph_components = obj.graphcomponent_set.all()
    for gc in graph_components:
        for feature in gc.features.all():
            features.append(feature.name)
            component_features.append(f"{gc.component.name} - {feature.name}")
    positions = [p.name for p in obj.positions.all()]

    doc = {
        "id": obj.id,
        "item_image": obj.item_image.id if obj.item_image else None,
        "item_part": obj.item_image.item_part.id if obj.item_image and obj.item_image.item_part else None,
        "image_iiif": obj.item_image.image.iiif.info if obj.item_image else None,
        "coordinates": json.dumps(obj.annotation) if isinstance(obj.annotation, dict) else str(obj.annotation),
        "is_annotated": obj.is_annotated(),
        "display_label": _display_label(obj),
        "repository_name": get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "repository_city": get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "shelfmark": get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "date": get_attr(obj, "item_image__item_part__historical_item__date__date"),
        "place": get_attr(obj, "hand__place"),
        "hand_name": get_attr(obj, "hand__name"),
        "components": unique_preserve_order(components),
        "features": unique_preserve_order(features),
        "component_features": unique_preserve_order(component_features),
        "positions": unique_preserve_order(positions),
        "allograph": get_attr(obj, "allograph__name"),
        "character": get_attr(obj, "allograph__character__name"),
        "character_type": get_attr(obj, "allograph__character__type"),
    }
    return drop_none(doc)


def _display_label(obj) -> str | None:
    item_part = getattr(getattr(obj, "item_image", None), "item_part", None)
    value = getattr(item_part, "display_label", None)
    if callable(value):
        value = value()
    if value is None:
        return None
    return str(value).strip() or None



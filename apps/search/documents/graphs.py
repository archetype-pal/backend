"""Document builder for graphs index."""

import json

from apps.annotations.models import GraphComponent


def build_graph_document(obj) -> dict:
    """Build a search document from a Graph instance."""
    components = [c.name for c in obj.components.all()]
    features = []
    component_features = []
    graph_components = (
        GraphComponent.objects.filter(graph=obj).select_related("component").prefetch_related("features")
    )
    for gc in graph_components:
        for feature in gc.features.all():
            features.append(feature.name)
            component_features.append(f"{gc.component.name} - {feature.name}")
    positions = [p.name for p in obj.positions.all()]

    doc = {
        "id": obj.id,
        "image_iiif": obj.item_image.image.iiif.info if obj.item_image else None,
        "coordinates": json.dumps(obj.annotation) if isinstance(obj.annotation, dict) else str(obj.annotation),
        "is_annotated": obj.is_annotated(),
        "repository_name": _get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "repository_city": _get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "shelfmark": _get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "date": _get_attr(obj, "item_image__item_part__historical_item__date__date"),
        "place": _get_attr(obj, "hand__place"),
        "hand_name": _get_attr(obj, "hand__name"),
        "components": components,
        "features": features,
        "component_features": component_features,
        "positions": positions,
        "allograph": _get_attr(obj, "allograph__name"),
        "character": _get_attr(obj, "allograph__character__name"),
        "character_type": _get_attr(obj, "allograph__character__type"),
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

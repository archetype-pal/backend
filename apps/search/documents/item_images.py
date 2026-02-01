"""Document builder for item_images index."""

from apps.annotations.models import GraphComponent


def build_item_image_document(obj) -> dict:
    """Build a search document from an ItemImage instance."""
    graphs = obj.graphs.all()
    components = []
    features = []
    component_features = []
    positions = []
    for graph in graphs:
        for component in graph.components.all():
            components.append(component.name)
        graph_components = GraphComponent.objects.filter(graph=graph).prefetch_related("features")
        for gc in graph_components:
            for feature in gc.features.all():
                features.append(feature.name)
                component_features.append(f"{gc.component.name} - {feature.name}")
        for position in graph.positions.all():
            positions.append(position.name)

    doc = {
        "id": obj.id,
        "image_iiif": obj.image.iiif.info,
        "locus": obj.locus,
        "repository_name": _get_attr(obj, "item_part__current_item__repository__name"),
        "repository_city": _get_attr(obj, "item_part__current_item__repository__place"),
        "shelfmark": _get_attr(obj, "item_part__current_item__shelfmark"),
        "date": _get_attr(obj, "item_part__historical_item__date__date"),
        "type": _get_attr(obj, "item_part__historical_item__type"),
        "number_of_annotations": obj.graphs.count(),
        "components": components,
        "features": features,
        "component_features": component_features,
        "positions": positions,
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

"""Document builder for item_images index."""


def build_item_image_document(obj) -> dict:
    """Build a search document from an ItemImage instance."""
    graphs = list(obj.graphs.all())
    components = []
    features = []
    component_features = []
    positions = []
    for graph in graphs:
        for component in graph.components.all():
            components.append(component.name)
        graph_components = graph.graphcomponent_set.all()
        for gc in graph_components:
            for feature in gc.features.all():
                features.append(feature.name)
                component_features.append(f"{gc.component.name} - {feature.name}")
        for position in graph.positions.all():
            positions.append(position.name)

    number_of_annotations = len(graphs)

    doc = {
        "id": obj.id,
        "image_iiif": obj.image.iiif.info,
        "locus": obj.locus,
        "repository_name": _get_attr(obj, "item_part__current_item__repository__name"),
        "repository_city": _get_attr(obj, "item_part__current_item__repository__place"),
        "shelfmark": _get_attr(obj, "item_part__current_item__shelfmark"),
        "date": _get_attr(obj, "item_part__historical_item__date__date"),
        "type": _get_attr(obj, "item_part__historical_item__type"),
        "number_of_annotations": number_of_annotations,
        "components": _unique_preserve_order(components),
        "features": _unique_preserve_order(features),
        "component_features": _unique_preserve_order(component_features),
        "positions": _unique_preserve_order(positions),
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


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    unique_values = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values

"""Document builder for item_images index."""

from apps.search.documents.utils import drop_none, get_attr, unique_preserve_order


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
        "item_part": obj.item_part_id,
        "image_iiif": obj.image.iiif.info,
        "locus": obj.locus,
        "repository_name": get_attr(obj, "item_part__current_item__repository__name"),
        "repository_city": get_attr(obj, "item_part__current_item__repository__place"),
        "shelfmark": get_attr(obj, "item_part__current_item__shelfmark"),
        "date": get_attr(obj, "item_part__historical_item__date__date"),
        "type": get_attr(obj, "item_part__historical_item__type"),
        "number_of_annotations": number_of_annotations,
        "components": unique_preserve_order(components),
        "features": unique_preserve_order(features),
        "component_features": unique_preserve_order(component_features),
        "positions": unique_preserve_order(positions),
        "tags": [tag.name for tag in obj.tags.all()],
    }
    return drop_none(doc)

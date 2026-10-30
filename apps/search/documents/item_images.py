from apps.search.documents.utils import display_label, drop_none, manuscript_context, unique_preserve_order


def build_item_image_document(obj) -> dict:
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

    context = manuscript_context(obj.item_part)
    doc = {
        "id": obj.id,
        "item_part": obj.item_part_id,
        "image_iiif": obj.image.iiif.info,
        "locus": obj.locus,
        "display_label": display_label(obj.item_part),
        "repository_name": context["repository_name"],
        "repository_city": context["repository_city"],
        "shelfmark": context["shelfmark"],
        "shelfmark_sort": context["shelfmark_sort"],
        "date": context["date"],
        "type": context["type"],
        "number_of_annotations": number_of_annotations,
        "components": unique_preserve_order(components),
        "features": unique_preserve_order(features),
        "component_features": unique_preserve_order(component_features),
        "positions": unique_preserve_order(positions),
        "tags": [tag.name for tag in obj.tags.all()],
    }
    return drop_none(doc)

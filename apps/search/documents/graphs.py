import json

from apps.search.documents.utils import display_label, drop_none, get_attr, manuscript_context, unique_preserve_order


def _allograph_label(obj) -> str | None:
    allograph_name = get_attr(obj, "allograph__name")
    character_name = get_attr(obj, "allograph__character__name")

    char = str(character_name).strip() if character_name else None
    allo = str(allograph_name).strip() if allograph_name else None

    if not char:
        return allo or None
    if not allo or char == allo:
        return char
    return f"{char}, {allo}"


def build_graph_document(obj) -> dict:
    components = [c.name for c in obj.components.all()]
    features = []
    component_features = []
    graph_components = obj.graphcomponent_set.all()
    for gc in graph_components:
        for feature in gc.features.all():
            features.append(feature.name)
            component_features.append(f"{gc.component.name} - {feature.name}")
    positions = [p.name for p in obj.positions.all()]

    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    doc = {
        "id": obj.id,
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "image_iiif": item_image.image.iiif.info if item_image else None,
        "coordinates": json.dumps(obj.annotation) if isinstance(obj.annotation, dict) else str(obj.annotation),
        "is_annotated": obj.is_annotated(),
        "display_label": display_label(item_part),
        **manuscript_context(item_part),
        "locus": get_attr(item_image, "locus"),
        "place": get_attr(obj, "hand__place"),
        "hand_name": get_attr(obj, "hand__name"),
        "scribe": get_attr(obj, "hand__scribe__name"),
        "components": unique_preserve_order(components),
        "features": unique_preserve_order(features),
        "component_features": unique_preserve_order(component_features),
        "positions": unique_preserve_order(positions),
        "allograph": _allograph_label(obj),
        "character": get_attr(obj, "allograph__character__name"),
        "character_type": get_attr(obj, "allograph__character__type"),
    }
    return drop_none(doc)

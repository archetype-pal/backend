from apps.search.documents.utils import display_label, drop_none, graph_taxonomy, manuscript_context


def build_item_image_document(obj) -> dict:
    graphs = list(obj.graphs.all())
    doc = {
        "id": obj.id,
        "item_part": obj.item_part_id,
        "image_iiif": obj.image.iiif.info,
        "locus": obj.locus,
        "display_label": display_label(obj.item_part),
        **manuscript_context(obj.item_part),
        "number_of_annotations": len(graphs),
        **graph_taxonomy(graphs),
        "tags": [tag.name for tag in obj.tags.all()],
    }
    return drop_none(doc)

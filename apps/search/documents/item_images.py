from apps.annotations.models import Graph
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
        # Glyphs only: text regions and editorial notes are not annotations a reader counts.
        "number_of_annotations": sum(graph.annotation_type == Graph.AnnotationType.IMAGE for graph in graphs),
        **graph_taxonomy(graphs),
        "tags": [tag.name for tag in obj.tags.all()],
    }
    return drop_none(doc)

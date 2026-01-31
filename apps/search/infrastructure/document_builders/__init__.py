from apps.search.domain import IndexType
from apps.search.infrastructure.document_builders.graphs import build_graph_document
from apps.search.infrastructure.document_builders.hands import build_hand_document
from apps.search.infrastructure.document_builders.item_images import build_item_image_document
from apps.search.infrastructure.document_builders.item_parts import build_item_part_document
from apps.search.infrastructure.document_builders.scribes import build_scribe_document

BUILDERS = {
    IndexType.ITEM_PARTS: build_item_part_document,
    IndexType.ITEM_IMAGES: build_item_image_document,
    IndexType.SCRIBES: build_scribe_document,
    IndexType.HANDS: build_hand_document,
    IndexType.GRAPHS: build_graph_document,
}


def build_document(index_type: IndexType, instance) -> dict:
    """Build a search document from a Django model instance."""
    builder = BUILDERS.get(index_type)
    if not builder:
        raise ValueError(f"No document builder for index type {index_type}")
    return builder(instance)

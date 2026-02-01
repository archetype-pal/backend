from apps.search.documents.graphs import build_graph_document
from apps.search.documents.hands import build_hand_document
from apps.search.documents.item_images import build_item_image_document
from apps.search.documents.item_parts import build_item_part_document
from apps.search.documents.scribes import build_scribe_document
from apps.search.types import IndexType

BUILDERS = {
    IndexType.ITEM_PARTS: build_item_part_document,
    IndexType.ITEM_IMAGES: build_item_image_document,
    IndexType.SCRIBES: build_scribe_document,
    IndexType.HANDS: build_hand_document,
    IndexType.GRAPHS: build_graph_document,
}

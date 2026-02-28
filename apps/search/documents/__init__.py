from collections.abc import Iterable
from typing import Any

from apps.search.contracts import SearchDocument
from apps.search.documents.clauses import build_clause_documents
from apps.search.documents.graphs import build_graph_document
from apps.search.documents.hands import build_hand_document
from apps.search.documents.item_images import build_item_image_document
from apps.search.documents.item_parts import build_item_part_document
from apps.search.documents.people import build_person_documents
from apps.search.documents.places import build_place_documents
from apps.search.documents.scribes import build_scribe_document
from apps.search.documents.texts import build_text_document
from apps.search.types import IndexType


def _to_document_iterable(result: Any) -> Iterable[SearchDocument]:
    if result is None:
        return []
    if isinstance(result, list):
        return result
    return [result]


def _as_many(builder):
    def wrapped(obj) -> Iterable[SearchDocument]:
        return _to_document_iterable(builder(obj))

    return wrapped


BUILDERS_MANY = {
    IndexType.ITEM_PARTS: _as_many(build_item_part_document),
    IndexType.ITEM_IMAGES: _as_many(build_item_image_document),
    IndexType.SCRIBES: _as_many(build_scribe_document),
    IndexType.HANDS: _as_many(build_hand_document),
    IndexType.GRAPHS: _as_many(build_graph_document),
    IndexType.TEXTS: _as_many(build_text_document),
    IndexType.CLAUSES: _as_many(build_clause_documents),
    IndexType.PEOPLE: _as_many(build_person_documents),
    IndexType.PLACES: _as_many(build_place_documents),
}

# Backward-compatible alias while services migrate to registry/contracts.
BUILDERS = BUILDERS_MANY

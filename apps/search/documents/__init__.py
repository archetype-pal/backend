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

__all__ = [
    "build_clause_documents",
    "build_graph_document",
    "build_hand_document",
    "build_item_image_document",
    "build_item_part_document",
    "build_person_documents",
    "build_place_documents",
    "build_scribe_document",
    "build_text_document",
    "normalize_builder",
]


def normalize_builder(builder: Any):
    """Wrap a document builder so it always yields an ``Iterable[SearchDocument]``.

    Individual builders may return a single dict, a list, or ``None`` (skip).
    Reindex wants one uniform iterable to ``extend`` regardless.
    """

    def wrapped(obj: Any) -> Iterable[SearchDocument]:
        result = builder(obj)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return [result]

    return wrapped

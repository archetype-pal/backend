"""One document per clause fragment in ``ImageText.content`` — a list, where
most builders return a single dict per row.
"""

from collections import Counter

from apps.search.documents.dpt_parser import extract_clauses
from apps.search.documents.utils import drop_none, region_coordinates, text_context


def _by_type_ordinal(clauses: list[dict]) -> dict[tuple[str, int], dict]:
    """Key clauses by (type, ordinal within that type).

    That pair is the one identity a clause keeps across an image's
    Transcription and its Translation, which mark up the same clauses in the
    same order over the same image regions.
    """
    seen: Counter = Counter()
    keyed = {}
    for clause in clauses:
        key = (clause["type"], seen[clause["type"]])
        seen[clause["type"]] += 1
        keyed[key] = clause
    return keyed


def _sibling_annotation_ids(obj) -> dict[tuple[str, int], int]:
    """Annotation ids the image's *other* text carries, keyed as above.

    Much of the migrated corpus links a clause to its image region on only one
    side of the transcription/translation pair, which left the other side with
    no region to crop a thumbnail from. Borrowing across the pair is safe:
    across the MoA corpus 2089 of the 2090 clauses linked on both sides point
    at the same annotation.
    """
    texts = getattr(getattr(obj, "item_image", None), "texts", None)
    if texts is None:
        return {}
    donors: dict[tuple[str, int], int] = {}
    for sibling in texts.all():
        if sibling.id == obj.id or not sibling.content:
            continue
        for key, clause in _by_type_ordinal(extract_clauses(sibling.content)).items():
            annotation_id = clause["annotation_id"]
            if isinstance(annotation_id, int):
                donors.setdefault(key, annotation_id)
    return donors


def build_clause_documents(obj) -> list[dict]:
    """One document per ``<span data-dpt="clause">``; ``[]`` if there is none.

    A clause with no linked annotation, its own or borrowed from the image's
    other text, is still indexed with a null ``annotation_id`` — its card falls
    back to the page scan. Dropping those empties the whole category on a corpus
    whose text-region links were never embedded.
    """
    if not obj.content:
        return []

    clauses = extract_clauses(obj.content)
    if not clauses:
        return []

    # Insertion order matches `clauses`, so index i of one lines up with the other.
    keys = list(_by_type_ordinal(clauses))
    donors = _sibling_annotation_ids(obj) if any(c["annotation_id"] is None for c in clauses) else {}
    annotation_ids = [
        clause["annotation_id"] if isinstance(clause["annotation_id"], int) else donors.get(key)
        for clause, key in zip(clauses, keys, strict=True)
    ]
    annotation_coordinates = region_coordinates(obj)
    shared = text_context(obj)

    documents = []
    for idx, (clause, annotation_id) in enumerate(zip(clauses, annotation_ids, strict=True)):
        doc = {
            "id": f"{obj.id}_{idx}",
            "clause_type": clause["type"],
            "content": clause["content"],
            "annotation_id": annotation_id,
            "annotation_coordinates": annotation_coordinates.get(annotation_id) if annotation_id else None,
            **shared,
        }
        documents.append(drop_none(doc, keep={"annotation_id", "annotation_coordinates"}))

    return documents

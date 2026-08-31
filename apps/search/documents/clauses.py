"""Document builder for clauses index.

Unlike other builders that return a single dict per model instance, this
builder returns a **list** of dicts — one Meilisearch document per clause
fragment found inside the ``ImageText.content`` HTML.
"""

from collections import Counter

from apps.search.documents.dpt_parser import extract_clauses
from apps.search.documents.utils import annotation_coordinates_map, drop_none, get_attr


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
    """Build search documents from an ImageText instance.

    Each ``<span data-dpt="clause" ...>`` in the content produces one
    document.  Returns ``[]`` if the content contains no clause markup.

    Clauses with no linked annotation — neither their own nor a borrowable one
    from the image's other text — are skipped: with no image region there is no
    clause image to show, and the clauses explore page is image-first.
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
    annotation_coordinates = annotation_coordinates_map([{"annotation_id": a} for a in annotation_ids])

    # Pre-fetch shared metadata once (same traversal as texts builder)
    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    historical_item = getattr(item_part, "historical_item", None) if item_part else None

    shared = {
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "text_type": obj.type,
        "repository_city": get_attr(obj, "item_image__item_part__current_item__repository__place"),
        "repository_name": get_attr(obj, "item_image__item_part__current_item__repository__name"),
        "shelfmark": get_attr(obj, "item_image__item_part__current_item__shelfmark"),
        "date": None,
        "date_min": None,
        "date_max": None,
        "catalogue_numbers": historical_item.get_catalogue_numbers_display() if historical_item else "",
        "locus": item_image.locus if item_image else "",
        "type": get_attr(obj, "item_image__item_part__historical_item__type"),
        "status": obj.status,
        "thumbnail_iiif": item_image.image.iiif.info if item_image else None,
    }

    if historical_item and historical_item.date:
        shared["date"] = historical_item.date.date
        shared["date_min"] = historical_item.date.min_weight
        shared["date_max"] = historical_item.date.max_weight

    documents = []
    for idx, (clause, annotation_id) in enumerate(zip(clauses, annotation_ids, strict=True)):
        if annotation_id is None:
            continue
        doc = {
            "id": f"{obj.id}_{idx}",
            "clause_type": clause["type"],
            "content": clause["content"],
            "annotation_id": annotation_id,
            "annotation_coordinates": annotation_coordinates.get(annotation_id),
            **shared,
        }
        documents.append(drop_none(doc, keep={"annotation_id", "annotation_coordinates"}))

    return documents

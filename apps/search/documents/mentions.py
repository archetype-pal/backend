"""One document per person or place mention in ``ImageText.content``.

The two indexes differ only in which spans are extracted and how their
documents are named; everything else — the manuscript context, the linked
region coordinates, the null-`annotation_id` handling — is the same.
"""

from collections.abc import Callable

from apps.search.documents.utils import drop_none, region_coordinates, text_context


def build_mention_documents(
    obj,
    *,
    extract: Callable[[str], list[dict]],
    id_prefix: str,
    type_key: str,
) -> list[dict]:
    """Documents for the mentions `extract` finds in `obj.content`; `[]` if none.

    Ids are derived (`<image_text id>_<id_prefix><ordinal>`), so the sync
    deletes them by the `image_text` field that `text_context` supplies.
    """
    if not obj.content:
        return []

    mentions = extract(obj.content)
    if not mentions:
        return []
    annotation_coordinates = region_coordinates(obj)
    shared = text_context(obj)

    documents = []
    for idx, mention in enumerate(mentions):
        raw_annotation_id = mention.get("annotation_id")
        annotation_id = raw_annotation_id if isinstance(raw_annotation_id, int) else None
        doc = {
            "id": f"{obj.id}_{id_prefix}{idx}",
            "name": mention["name"],
            type_key: mention["type"],
            "ref": mention["ref"],
            "annotation_id": annotation_id,
            "annotation_coordinates": annotation_coordinates.get(annotation_id) if annotation_id is not None else None,
            **shared,
        }
        documents.append(drop_none(doc, keep={"annotation_id", "annotation_coordinates"}))

    return documents

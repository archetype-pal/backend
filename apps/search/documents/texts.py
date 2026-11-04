from apps.diplomatic.models import CharterEntity
from apps.search.documents.dpt_parser import extract_all
from apps.search.documents.utils import (
    drop_none,
    region_coordinates,
    strip_html_for_search,
    text_context,
    unique_preserve_order,
)

# The people a scholar approved in each role (W2.1), one facet per role. The
# `<persName>` markup behind `people` says who a charter names but not in what
# capacity, so only these can tell its granter from its witnesses. Each keeps
# the name as the charter writes it, as `people` and the network do.
ROLE_FACETS = {
    CharterEntity.Role.GRANTER: "granters",
    CharterEntity.Role.BENEFICIARY: "beneficiaries",
    CharterEntity.Role.WITNESS: "witnesses",
}


def build_text_document(obj) -> dict:
    doc = {
        "id": obj.id,
        **text_context(obj),
        "content": strip_html_for_search(obj.content) if obj.content else "",
        "language": obj.language,
    }
    # The texts index is one document per row, so `image_text` (the fan-out
    # indexes' parent key) would only duplicate `id`.
    del doc["image_text"]

    if obj.content:
        extracted = extract_all(obj.content)
        doc["places"] = unique_preserve_order([place["name"] for place in extracted["places"]])
        doc["people"] = unique_preserve_order([person["name"] for person in extracted["people"]])
        doc["annotation_id"] = _first_annotation_id(extracted)
        doc["annotation_coordinates"] = region_coordinates(obj).get(doc["annotation_id"])
    else:
        doc["places"] = []
        doc["people"] = []
        doc["annotation_id"] = None
        doc["annotation_coordinates"] = None

    names: dict[str, list[str]] = {facet: [] for facet in ROLE_FACETS.values()}
    for entity in obj.diplomatic_entities.all():
        if facet := ROLE_FACETS.get(entity.role):
            names[facet].append(entity.name)
    doc.update({facet: unique_preserve_order(values) for facet, values in names.items()})

    return drop_none(doc, keep={"annotation_id", "annotation_coordinates"})


def _first_annotation_id(extracted: dict) -> int | None:
    for group in ("clauses", "places", "people"):
        for entry in extracted.get(group, []):
            annotation_id = entry.get("annotation_id")
            if isinstance(annotation_id, int):
                return annotation_id
    return None

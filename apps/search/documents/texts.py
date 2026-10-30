from apps.search.documents.dpt_parser import extract_all
from apps.search.documents.utils import drop_none, region_coordinates, strip_html_for_search, text_context


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
        doc["places"] = list(dict.fromkeys(place["name"] for place in extracted["places"]))
        doc["people"] = list(dict.fromkeys(person["name"] for person in extracted["people"]))
        doc["annotation_id"] = _first_annotation_id(extracted)
        doc["annotation_coordinates"] = region_coordinates(obj).get(doc["annotation_id"])
    else:
        doc["places"] = []
        doc["people"] = []
        doc["annotation_id"] = None
        doc["annotation_coordinates"] = None

    return drop_none(doc, keep={"annotation_id", "annotation_coordinates"})


def _first_annotation_id(extracted: dict) -> int | None:
    for group in ("clauses", "places", "people"):
        for entry in extracted.get(group, []):
            annotation_id = entry.get("annotation_id")
            if isinstance(annotation_id, int):
                return annotation_id
    return None

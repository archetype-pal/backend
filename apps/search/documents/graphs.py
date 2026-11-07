from apps.search.documents.utils import (
    annotation_json,
    display_label,
    drop_none,
    get_attr,
    graph_taxonomy,
    manuscript_context,
)
from apps.search.types import VectorSearch
from apps.vision.services import glyph_search

GLYPH_VECTORS = VectorSearch(embedder="glyph", dimensions=glyph_search.DIMENSIONS, flag="has_glyph_vector")


def _allograph_label(obj) -> str | None:
    allograph_name = get_attr(obj, "allograph__name")
    character_name = get_attr(obj, "allograph__character__name")

    char = str(character_name).strip() if character_name else None
    allo = str(allograph_name).strip() if allograph_name else None

    if not char:
        return allo or None
    if not allo or char == allo:
        return char
    return f"{char}, {allo}"


def _scribe_name(obj) -> str | None:
    scribe = getattr(getattr(obj, "hand", None), "scribe", None)
    # DigiPal's placeholder is not a scribe (`Scribe.is_placeholder`).
    if scribe is None or scribe.is_placeholder:
        return None
    return str(scribe.name)


def build_graph_document(obj) -> dict:
    item_image = obj.item_image
    item_part = getattr(item_image, "item_part", None)
    doc = {
        "id": obj.id,
        "item_image": item_image.id if item_image else None,
        "item_part": item_part.id if item_part else None,
        "image_iiif": item_image.image.iiif.info if item_image else None,
        "coordinates": annotation_json(obj.annotation),
        "is_annotated": obj.is_described(),
        "display_label": display_label(item_part),
        **manuscript_context(item_part),
        "locus": get_attr(item_image, "locus"),
        "place": get_attr(obj, "hand__place"),
        "hand_name": get_attr(obj, "hand__name"),
        "scribe": _scribe_name(obj),
        **graph_taxonomy([obj]),
        "allograph": _allograph_label(obj),
        "character": get_attr(obj, "allograph__character__name"),
        "character_type": get_attr(obj, "allograph__character__type"),
    }
    vector = glyph_search.search_vector(obj)
    # Null, never left out: see `VectorSearch`.
    doc[GLYPH_VECTORS.flag] = vector is not None
    doc["_vectors"] = {GLYPH_VECTORS.embedder: vector}
    return drop_none(doc)

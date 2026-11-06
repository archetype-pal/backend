"""One document per place mention in ``ImageText.content`` — see `mentions.py`."""

from apps.search.documents.dpt_parser import extract_places_detailed
from apps.search.documents.mentions import build_mention_documents


def build_place_documents(obj) -> list[dict]:
    return build_mention_documents(obj, extract=extract_places_detailed, id_prefix="l", type_key="place_type")

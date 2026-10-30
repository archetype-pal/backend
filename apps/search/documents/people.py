"""One document per person mention in ``ImageText.content`` — see `mentions.py`."""

from apps.search.documents.dpt_parser import extract_people_detailed
from apps.search.documents.mentions import build_mention_documents


def build_person_documents(obj) -> list[dict]:
    return build_mention_documents(obj, extract=extract_people_detailed, id_prefix="p", type_key="person_type")

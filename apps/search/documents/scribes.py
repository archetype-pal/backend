from apps.search.documents.utils import drop_none


def build_scribe_document(obj) -> dict:
    period = str(obj.period) if obj.period else ""
    doc = {
        "id": obj.id,
        "name": obj.name,
        "period": period,
        "scriptorium": obj.scriptorium or "",
    }
    return drop_none(doc)

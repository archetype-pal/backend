"""Document builder for scribes index."""

from apps.search.documents.utils import drop_none


def build_scribe_document(obj) -> dict:
    """Build a search document from a Scribe instance."""
    period = str(obj.period) if obj.period else ""
    doc = {
        "id": obj.id,
        "name": obj.name,
        "period": period,
        "scriptorium": obj.scriptorium or "",
    }
    return drop_none(doc)

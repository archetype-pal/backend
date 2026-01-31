"""Document builder for scribes index."""


def build_scribe_document(obj) -> dict:
    """Build a search document from a Scribe instance."""
    period = str(obj.period) if obj.period else ""
    doc = {
        "id": obj.id,
        "name": obj.name,
        "period": period,
        "scriptorium": obj.scriptorium or "",
    }
    return _drop_none(doc)


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}

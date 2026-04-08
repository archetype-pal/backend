"""Shared helpers for document builders."""


def get_attr(obj, path: str):
    """Follow relation path (e.g. ``item_part__current_item__shelfmark``) and return value or None."""
    for part in path.split("__"):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return str(obj) if obj is not None else None


def drop_none(d: dict) -> dict:
    """Return a copy with None values removed (Meilisearch-friendly)."""
    return {k: v for k, v in d.items() if v is not None}


def unique_preserve_order(values: list[str]) -> list[str]:
    """Deduplicate a list while preserving insertion order."""
    seen = set()
    unique_values = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return unique_values

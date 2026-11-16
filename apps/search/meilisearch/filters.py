from apps.search.filter_contract import escape_filter_value as _escape
from apps.search.types import DateWindow, FilterSpec


def _date_window_parts(field: str, window: DateWindow) -> list[str]:
    parts = []
    if window.min_date is not None:
        parts.append(f"{field}_min >= {window.min_date}")
    if window.max_date is not None:
        parts.append(f"{field}_max <= {window.max_date}")
    if window.at_most_or_least and window.date_diff is not None and window.min_date is not None:
        if window.at_most_or_least == "at most":
            parts.append(f"{field}_max <= {window.min_date + window.date_diff}")
        elif window.at_most_or_least == "at least":
            parts.append(f"{field}_max >= {window.min_date + window.date_diff}")
    return parts


def build_meilisearch_filter(spec: FilterSpec) -> str | None:
    """Compile a FilterSpec (incl. the manuscript date window) to a Meilisearch filter string.

    Returns None when there are no conditions. Expects a spec that already
    passed `filter_contract.sanitize_filter_spec` — `parsers.parse_search_query`
    does that at the HTTP boundary, so every attribute here is filterable on
    the target index.
    """
    parts = []

    for attr, value in spec.equal.items():
        if value is None:
            continue
        if isinstance(value, list):
            if value:
                parts.append("(" + " OR ".join(f"{attr} = {_escape(v)}" for v in value) + ")")
        else:
            parts.append(f"{attr} = {_escape(value)}")

    for attr, values in spec.facets.items():
        parts.extend(f"{attr} = {_escape(v)}" for v in values)

    for attr, value in spec.not_equal.items():
        if value is None:
            continue
        if isinstance(value, list):
            parts.extend(f"{attr} != {_escape(v)}" for v in value if v is not None)
        else:
            parts.append(f"{attr} != {_escape(value)}")

    for attr, (lo, hi) in spec.range_.items():
        if lo is not None:
            parts.append(f"{attr} >= {lo}")
        if hi is not None:
            parts.append(f"{attr} <= {hi}")

    parts.extend(
        _date_window_parts("date", DateWindow(spec.min_date, spec.max_date, spec.at_most_or_least, spec.date_diff))
    )
    for field, window in spec.date_windows.items():
        parts.extend(_date_window_parts(field, window))

    parts.extend(f"{attr} IS NULL" for attr in spec.empty)
    parts.extend(f"{attr} IS NOT NULL" for attr in spec.not_empty)

    if spec.qb_expr:
        parts.append(f"({spec.qb_expr})")

    if not parts:
        return None
    return " AND ".join(parts)

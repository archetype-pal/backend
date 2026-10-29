from apps.search.filter_contract import escape_filter_value as _escape
from apps.search.types import FilterSpec


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
                escaped = [_escape(v) for v in value]
                parts.append(f"({attr} = {escaped[0]}" + "".join(f" OR {attr} = {v}" for v in escaped[1:]) + ")")
        else:
            parts.append(f"{attr} = {_escape(value)}")

    for attr, value in spec.not_equal.items():
        if value is None:
            continue
        if isinstance(value, list):
            for v in value:
                if v is not None:
                    parts.append(f"{attr} != {_escape(v)}")
        else:
            parts.append(f"{attr} != {_escape(value)}")

    for attr, (lo, hi) in spec.range_.items():
        if lo is not None:
            parts.append(f"{attr} >= {lo}")
        if hi is not None:
            parts.append(f"{attr} <= {hi}")

    if spec.min_date is not None:
        parts.append(f"date_min >= {spec.min_date}")
    if spec.max_date is not None:
        parts.append(f"date_max <= {spec.max_date}")
    if spec.at_most_or_least and spec.date_diff is not None and spec.min_date is not None:
        if spec.at_most_or_least == "at most":
            parts.append(f"date_max <= {spec.min_date + spec.date_diff}")
        elif spec.at_most_or_least == "at least":
            parts.append(f"date_max >= {spec.min_date + spec.date_diff}")

    for attr in spec.empty:
        parts.append(f"{attr} IS NULL")
    for attr in spec.not_empty:
        parts.append(f"{attr} IS NOT NULL")

    if spec.qb_expr:
        parts.append(f"({spec.qb_expr})")

    if not parts:
        return None
    return " AND ".join(parts)

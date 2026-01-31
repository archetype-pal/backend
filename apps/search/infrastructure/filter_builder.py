"""Build Meilisearch filter expression from FilterSpec and manuscript date params."""


def build_meilisearch_filter(spec) -> str | None:
    """
    Convert FilterSpec (and manuscript min_date, max_date, at_most_or_least, date_diff)
    into a Meilisearch filter expression string.
    Returns None if no filter conditions.
    """
    parts = []

    # Equality: field = value or field IN [v1, v2]
    for attr, value in spec.equal.items():
        if value is None:
            continue
        if isinstance(value, list):
            if value:
                escaped = [_escape(v) for v in value]
                parts.append(f"({attr} = {escaped[0]}" + "".join(f" OR {attr} = {v}" for v in escaped[1:]) + ")")
        else:
            parts.append(f"{attr} = {_escape(value)}")

    # Not equal
    for attr, value in spec.not_equal.items():
        if value is not None:
            parts.append(f"{attr} != {_escape(value)}")

    # IN (explicit list)
    for attr, values in spec.in_.items():
        if values:
            escaped = [_escape(v) for v in values]
            parts.append(f"({attr} = {escaped[0]}" + "".join(f" OR {attr} = {v}" for v in escaped[1:]) + ")")

    # Numeric range
    for attr, (lo, hi) in spec.range_.items():
        if lo is not None:
            parts.append(f"{attr} >= {lo}")
        if hi is not None:
            parts.append(f"{attr} <= {hi}")

    # Manuscript date range
    if spec.min_date is not None:
        parts.append(f"date_min >= {spec.min_date}")
    if spec.max_date is not None:
        parts.append(f"date_max <= {spec.max_date}")
    if spec.at_most_or_least and spec.date_diff is not None and spec.min_date is not None:
        if spec.at_most_or_least == "at most":
            parts.append(f"date_max <= {spec.min_date + spec.date_diff}")
        elif spec.at_most_or_least == "at least":
            parts.append(f"date_max >= {spec.min_date + spec.date_diff}")

    if not parts:
        return None
    return " AND ".join(parts)


def _escape(value) -> str:
    """Escape value for Meilisearch filter (strings in double quotes)."""
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace('"', '\\"')
    return f'"{s}"'

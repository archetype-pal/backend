from apps.search.registry import get_registration
from apps.search.types import FilterSpec, IndexType


def escape_filter_value(value: object) -> str:
    """Escape a value for a Meilisearch filter literal.

    Numbers pass through bare; everything else is wrapped in double quotes with
    backslashes and embedded double quotes backslash-escaped, so a value can't
    break out of the quoted literal. Backslashes go first: Meilisearch reads a
    backslash as escaping the next character, so a lone one (say a trailing
    `foo\\`) would swallow the closing quote. Single source of truth shared by
    the FilterSpec builder (`meilisearch/filters.py`) and the query-builder tree
    parser (`qb_parser.py`).
    """
    if isinstance(value, (int, float)):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def allowed_filter_attributes(index_type: IndexType) -> set[str]:
    return set(get_registration(index_type).filterable_attributes)


def normalize_filter_attribute(attr: str, index_type: IndexType) -> str:
    """Accept the frontend's `<attr>_exact` spelling for a filterable attribute."""
    if attr.endswith("_exact") and attr[:-6] in allowed_filter_attributes(index_type):
        return attr[:-6]
    return attr


def sanitize_filter_spec(spec: FilterSpec, index_type: IndexType) -> FilterSpec:
    """Drop every clause naming an attribute the index cannot filter on (Meilisearch would 400)."""
    allowed = allowed_filter_attributes(index_type)

    def keep(mapping: dict) -> dict:
        return {attr: value for attr, value in mapping.items() if attr in allowed}

    # The date window compiles to `date_min` / `date_max` clauses.
    has_date_min, has_date_max = "date_min" in allowed, "date_max" in allowed
    return FilterSpec(
        equal=keep(spec.equal),
        not_equal=keep(spec.not_equal),
        range_=keep(spec.range_),
        min_date=spec.min_date if has_date_min else None,
        max_date=spec.max_date if has_date_max else None,
        at_most_or_least=spec.at_most_or_least if has_date_max else None,
        date_diff=spec.date_diff if has_date_max else None,
        contains=keep(spec.contains),
        starts_with=keep(spec.starts_with),
        empty=[a for a in spec.empty if a in allowed],
        not_empty=[a for a in spec.not_empty if a in allowed],
        qb_expr=spec.qb_expr,
    )

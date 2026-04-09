"""Parse request query params into SearchQuery, FilterSpec, SortSpec."""

from typing import Any, cast

from apps.search.filter_contract import (
    allowed_filter_attributes,
    default_facet_attributes,
    normalize_filter_attribute,
    requested_facet_attributes,
    sanitize_filter_spec,
)
from apps.search.index_metadata import SORTABLE_ATTRIBUTES
from apps.search.qb_parser import parse_qb_param
from apps.search.registry import get_registration
from apps.search.types import FilterSpec, IndexType, SearchQuery, SortSpec


def _and_qb_expr(a: str | None, b: str | None) -> str | None:
    parts = [p for p in (a, b) if p]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return " AND ".join(f"({p})" for p in parts)


def _merge_filter_with_qb(base: FilterSpec, qb: FilterSpec | None) -> FilterSpec:
    if qb is None:
        return base
    return FilterSpec(
        equal=base.equal,
        not_equal=base.not_equal,
        in_=base.in_,
        range_=base.range_,
        min_date=base.min_date,
        max_date=base.max_date,
        at_most_or_least=base.at_most_or_least,
        date_diff=base.date_diff,
        contains={**base.contains, **qb.contains},
        starts_with={**base.starts_with, **qb.starts_with},
        empty=list(dict.fromkeys([*base.empty, *qb.empty])),
        not_empty=list(dict.fromkeys([*base.not_empty, *qb.not_empty])),
        qb_expr=_and_qb_expr(base.qb_expr, qb.qb_expr),
    )


def parse_search_query(
    query_params: Any,
    index_type: IndexType,
    default_limit: int = 20,
    max_limit: int = 100,
) -> SearchQuery:
    """
    Build SearchQuery from request query params.
    Supports: q, filter (structured as param=value), sort, limit, offset.
    Manuscript-specific: min_date, max_date, at_most_or_least, date_diff.
    """
    q = (query_params.get("q") or "").strip()
    limit = _int_param(query_params.get("limit"), default_limit, 1, max_limit) or default_limit
    offset = _int_param(query_params.get("offset"), 0, 0, None) or 0

    filter_spec = _parse_filter_spec(query_params, index_type)
    sort_spec = _parse_sort_spec(query_params, index_type)
    matching_strategy = _parse_matching_strategy(query_params.get("matching_strategy"))
    attributes_to_search_on = _parse_attributes_to_search_on(query_params, index_type)
    attributes_to_retrieve = _parse_csv_param(query_params.get("attributes_to_retrieve"))

    return SearchQuery(
        q=q,
        filter_spec=filter_spec,
        sort_spec=sort_spec,
        limit=limit,
        offset=offset,
        matching_strategy=matching_strategy,
        attributes_to_search_on=attributes_to_search_on,
        attributes_to_retrieve=attributes_to_retrieve,
    )


def _normalize_facet_attr(attr: str, index_type: IndexType) -> str:
    """Map frontend facet key to Meilisearch filterable attribute."""
    return normalize_filter_attribute(attr, index_type)


def _parse_filter_spec(query_params: Any, index_type: IndexType) -> FilterSpec:
    reserved = {
        "q",
        "sort",
        "ordering",
        "limit",
        "offset",
        "facets",
        "page",
        "page_size",
        "matching_strategy",
        "search_field",
        "attributes_to_retrieve",
        "qb",
        "compare",
        "keyword",
        "advanced",
        "view",
        "format",
        "scope",
    }
    equal: dict[str, str | int | float | list[str | int | float]] = {}
    not_equal: dict[str, str | int | float | list[str | int | float]] = {}
    in_: dict[str, list[str | int | float]] = {}
    range_: dict[str, tuple[int | float | None, int | float | None]] = {}
    contains: dict[str, str] = {}
    starts_with: dict[str, str] = {}
    empty_attrs: list[str] = []
    not_empty_attrs: list[str] = []

    if hasattr(query_params, "getlist"):
        for entry in query_params.getlist("selected_facets") or []:
            entry = (entry or "").strip()
            if not entry:
                continue
            if ":" in entry:
                attr, _, val = entry.partition(":")
                attr, val = attr.strip(), val.strip()
                if attr and val:
                    normalized = _normalize_facet_attr(attr, index_type)
                    equal[normalized] = val
    elif isinstance(query_params.get("selected_facets"), list):
        for entry in query_params.get("selected_facets") or []:
            entry = str(entry or "").strip()
            if ":" in entry:
                attr, _, val = entry.partition(":")
                attr, val = attr.strip(), val.strip()
                if attr and val:
                    normalized = _normalize_facet_attr(attr, index_type)
                    equal[normalized] = val

    for key in query_params:
        if key in reserved or key == "selected_facets":
            continue
        if hasattr(query_params, "getlist"):
            values = [str(v).strip() for v in query_params.getlist(key) if v and str(v).strip()]
        else:
            value = query_params.get(key)
            values = [str(value).strip()] if value and str(value).strip() else []
        if not values:
            continue
        if key.endswith("__not"):
            attr = key[:-5]
            normalized = _normalize_facet_attr(attr, index_type)
            prev = not_equal.get(normalized)
            if prev is None:
                not_equal[normalized] = values[0] if len(values) == 1 else list(values)
            elif isinstance(prev, list):
                not_equal[normalized] = list(dict.fromkeys([*prev, *values]))
            else:
                not_equal[normalized] = list(dict.fromkeys([str(prev), *values]))
        elif key.endswith("__contains"):
            attr = key[:-10]
            normalized = _normalize_facet_attr(attr, index_type)
            if values:
                contains[normalized] = values[0]
        elif key.endswith("__startswith"):
            attr = key[:-12]
            normalized = _normalize_facet_attr(attr, index_type)
            if values:
                starts_with[normalized] = values[0]
        elif key.endswith("__empty") and values and values[0].lower() in {"1", "true", "yes"}:
            attr = key[: -len("__empty")]
            normalized = _normalize_facet_attr(attr, index_type)
            empty_attrs.append(normalized)
        elif key.endswith("__not_empty") and values and values[0].lower() in {"1", "true", "yes"}:
            attr = key[: -len("__not_empty")]
            normalized = _normalize_facet_attr(attr, index_type)
            not_empty_attrs.append(normalized)
        elif key.endswith("__min"):
            attr = key[:-5]
            lo = _float_param(values[0])
            normalized = _normalize_facet_attr(attr, index_type)
            current = range_.get(normalized, (None, None))
            range_[normalized] = (lo, current[1])
        elif key.endswith("__max"):
            attr = key[:-5]
            hi = _float_param(values[0])
            normalized = _normalize_facet_attr(attr, index_type)
            current = range_.get(normalized, (None, None))
            range_[normalized] = (current[0], hi)
        elif len(values) == 1:
            normalized = _normalize_facet_attr(key, index_type)
            equal[normalized] = values[0]
        else:
            normalized = _normalize_facet_attr(key, index_type)
            equal[normalized] = cast(list[str | int | float], values)

    min_date = _int_param(query_params.get("min_date"))
    max_date = _int_param(query_params.get("max_date"))
    at_most_or_least = (query_params.get("at_most_or_least") or "").strip() or None
    date_diff = _int_param(query_params.get("date_diff"))

    base = FilterSpec(
        equal=equal,
        not_equal=not_equal,
        in_=in_,
        range_=range_,
        min_date=min_date,
        max_date=max_date,
        at_most_or_least=at_most_or_least,
        date_diff=date_diff,
        contains=contains,
        starts_with=starts_with,
        empty=list(dict.fromkeys(empty_attrs)),
        not_empty=list(dict.fromkeys(not_empty_attrs)),
    )
    qb_raw = (query_params.get("qb") or "").strip()
    qb_spec = parse_qb_param(qb_raw, index_type) if qb_raw else None
    merged = _merge_filter_with_qb(base, qb_spec)
    return sanitize_filter_spec(merged, index_type)


def _parse_sort_spec(query_params: Any, index_type: IndexType) -> SortSpec | None:
    sort_param = (query_params.get("sort") or query_params.get("ordering") or "").strip()
    if not sort_param:
        return None

    allowed = set(SORTABLE_ATTRIBUTES.get(index_type, []))
    ascending = True
    attribute = sort_param
    if attribute.startswith("-"):
        ascending = False
        attribute = attribute[1:]
    elif ":asc" in attribute:
        attribute, _ = attribute.split(":asc", 1)
        attribute = attribute.strip()
        ascending = True
    elif ":desc" in attribute:
        attribute, _ = attribute.split(":desc", 1)
        attribute = attribute.strip()
        ascending = False

    if allowed and attribute not in allowed:
        return None
    return SortSpec(attribute=attribute, ascending=ascending)


def _int_param(
    value: object,
    default: int | None = None,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int | None:
    if value is None or value == "":
        return default
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return default
    try:
        number = int(value)
        if min_val is not None and number < min_val:
            number = min_val
        if max_val is not None and number > max_val:
            number = max_val
        return number
    except TypeError, ValueError:
        return default


def _float_param(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _parse_csv_param(value: object) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _parse_matching_strategy(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    if raw in {"all", "last"}:
        return raw
    if raw == "any":
        return "last"
    return None


def _parse_attributes_to_search_on(query_params: Any, index_type: IndexType) -> list[str]:
    requested = _parse_csv_param(query_params.get("search_field"))
    if not requested:
        return []
    allowed = set(get_registration(index_type).searchable_attributes)
    return [field for field in requested if field in allowed]


def parse_facet_attributes(query_params: Any, index_type: IndexType) -> list[str]:
    facets_param = (query_params.get("facets") or "").strip()
    if facets_param:
        return requested_facet_attributes(facets_param, index_type)
    allowed = allowed_filter_attributes(index_type)
    return [facet for facet in default_facet_attributes(index_type) if facet in allowed]

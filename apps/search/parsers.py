"""HTTP query parameters → `SearchQuery`. Nothing past this module sees a raw query string."""

from dataclasses import replace
from typing import Any

from apps.common.query_params import TRUE_VALUES
from apps.search.filter_contract import normalize_filter_attribute, sanitize_filter_spec
from apps.search.qb_parser import parse_qb_param
from apps.search.registry import get_registration
from apps.search.types import FilterSpec, IndexType, SearchQuery, SortSpec

# Meilisearch rejects an offset past 2**64 - 1, so an unbounded one is a 500.
# No hit lies past the indexes' `maxTotalHits` (`MeilisearchIndexWriter.MAX_TOTAL_HITS`),
# so clamping there changes no results.
MAX_OFFSET = 1_000_000

# List results crop these attributes in `_formatted` (Meilisearch `attributesToCrop`): the
# texts index would otherwise return every hit's whole transcription, which the result list
# only shows as a snippet around the first match. The raw attribute is still returned in full.
_CROPPED_IN_LISTS: dict[IndexType, list[str]] = {IndexType.TEXTS: ["content"]}
LIST_CROP_WORDS = 60

# Query parameters that are not filters.
_RESERVED = {
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
    "selected_facets",
    "min_date",
    "max_date",
    "at_most_or_least",
    "date_diff",
}


def _values(query_params: Any, key: str) -> list[str]:
    """Every non-blank value for `key` (a QueryDict may carry several)."""
    raw = query_params.getlist(key) if hasattr(query_params, "getlist") else query_params.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    return [str(value).strip() for value in raw if value and str(value).strip()]


def parse_search_query(
    query_params: Any,
    index_type: IndexType,
    default_limit: int = 20,
    max_limit: int = 100,
) -> SearchQuery:
    """Build SearchQuery from request query params: q, filters, sort, limit, offset."""
    searchable = set(get_registration(index_type).searchable_attributes)
    return SearchQuery(
        q=(query_params.get("q") or "").strip(),
        filter_spec=_parse_filter_spec(query_params, index_type),
        sort_spec=_parse_sort_spec(query_params, index_type),
        limit=_int_param(query_params.get("limit"), default_limit, 1, max_limit) or default_limit,
        offset=_int_param(query_params.get("offset"), 0, 0, MAX_OFFSET) or 0,
        matching_strategy=_parse_matching_strategy(query_params.get("matching_strategy")),
        attributes_to_search_on=[f for f in _csv(query_params.get("search_field")) if f in searchable],
        attributes_to_retrieve=_csv(query_params.get("attributes_to_retrieve")),
        attributes_to_crop=_CROPPED_IN_LISTS.get(index_type, []),
        crop_length=LIST_CROP_WORDS if index_type in _CROPPED_IN_LISTS else None,
    )


def _parse_filter_spec(query_params: Any, index_type: IndexType) -> FilterSpec:
    """`attr=v` (OR of several), `attr__not=v`, `attr__contains=v`, `attr__startswith=v`,
    `attr__empty=true`, `attr__not_empty=true`, `attr__min=n`, `attr__max=n`,
    `selected_facets=attr:value`, the manuscript date window, and a `qb` tree."""
    spec = FilterSpec(
        min_date=_int_param(query_params.get("min_date")),
        max_date=_int_param(query_params.get("max_date")),
        at_most_or_least=(query_params.get("at_most_or_least") or "").strip() or None,
        date_diff=_int_param(query_params.get("date_diff")),
    )

    def attr(key: str, suffix: str) -> str:
        return normalize_filter_attribute(key[: -len(suffix)], index_type)

    for entry in _values(query_params, "selected_facets"):
        name, _, value = entry.partition(":")
        if name.strip() and value.strip():
            spec.equal[normalize_filter_attribute(name.strip(), index_type)] = value.strip()

    for key in query_params:
        if key in _RESERVED or not (values := _values(query_params, key)):
            continue
        if key.endswith("__not"):
            name = attr(key, "__not")
            previous = spec.not_equal.get(name)
            existing = previous if isinstance(previous, list) else [] if previous is None else [previous]
            merged = [*existing, *values]
            spec.not_equal[name] = merged[0] if len(merged) == 1 else list(dict.fromkeys(map(str, merged)))
        elif key.endswith("__contains"):
            spec.contains[attr(key, "__contains")] = values[0]
        elif key.endswith("__startswith"):
            spec.starts_with[attr(key, "__startswith")] = values[0]
        elif key.endswith("__not_empty"):
            if values[0].lower() in TRUE_VALUES:
                spec.not_empty.append(attr(key, "__not_empty"))
        elif key.endswith("__empty"):
            if values[0].lower() in TRUE_VALUES:
                spec.empty.append(attr(key, "__empty"))
        elif key.endswith("__min"):
            name = attr(key, "__min")
            spec.range_[name] = (_float_param(values[0]), spec.range_.get(name, (None, None))[1])
        elif key.endswith("__max"):
            name = attr(key, "__max")
            spec.range_[name] = (spec.range_.get(name, (None, None))[0], _float_param(values[0]))
        else:
            spec.equal[normalize_filter_attribute(key, index_type)] = values[0] if len(values) == 1 else list(values)

    spec.empty = list(dict.fromkeys(spec.empty))
    spec.not_empty = list(dict.fromkeys(spec.not_empty))

    qb = parse_qb_param((query_params.get("qb") or "").strip(), index_type)
    if qb is not None:
        exprs = [e for e in (spec.qb_expr, qb.qb_expr) if e]
        spec = replace(
            spec,
            contains={**spec.contains, **qb.contains},
            starts_with={**spec.starts_with, **qb.starts_with},
            empty=list(dict.fromkeys([*spec.empty, *qb.empty])),
            not_empty=list(dict.fromkeys([*spec.not_empty, *qb.not_empty])),
            qb_expr=" AND ".join(f"({e})" for e in exprs) if len(exprs) > 1 else (exprs[0] if exprs else None),
        )
    return sanitize_filter_spec(spec, index_type)


def _parse_sort_spec(query_params: Any, index_type: IndexType) -> SortSpec | None:
    """`-attr`, `attr`, `attr:asc` or `attr:desc`; an attribute the index cannot sort on is ignored."""
    raw = (query_params.get("sort") or query_params.get("ordering") or "").strip()
    if not raw:
        return None
    ascending = not raw.startswith("-") and ":desc" not in raw
    attribute = raw.lstrip("-").split(":", 1)[0].strip()
    allowed = set(get_registration(index_type).sortable_attributes)
    # The frontend suffixes exact-match sortable fields with `_exact`, matching the filter convention.
    if attribute.endswith("_exact") and attribute[:-6] in allowed:
        attribute = attribute[:-6]
    if allowed and attribute not in allowed:
        return None
    return SortSpec(attribute=attribute, ascending=ascending)


def _int_param(
    value: object,
    default: int | None = None,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int | None:
    if value is None or value == "" or not isinstance(value, (int, float, str, bytes, bytearray)):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):  # fmt: skip
        return default
    if min_val is not None:
        number = max(number, min_val)
    if max_val is not None:
        number = min(number, max_val)
    return number


def _float_param(value: object) -> float | None:
    if value is None or value == "" or not isinstance(value, (int, float, str, bytes, bytearray)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):  # fmt: skip
        return None


def _csv(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _parse_matching_strategy(value: object) -> str | None:
    raw = str(value or "").strip().lower()
    return {"all": "all", "last": "last", "any": "last"}.get(raw)


def parse_facet_attributes(query_params: Any, index_type: IndexType) -> list[str]:
    """`?facets=a,b` restricted to filterable attributes, else the index's default facet set."""
    registration = get_registration(index_type)
    allowed = set(registration.filterable_attributes)
    requested = _csv(query_params.get("facets")) or registration.default_facet_attributes
    return [facet for facet in requested if facet in allowed]

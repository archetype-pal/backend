"""Centralized filter/facet contract helpers for search parsing."""

from apps.search.registry import get_registration
from apps.search.types import FilterSpec, IndexType


def allowed_filter_attributes(index_type: IndexType) -> set[str]:
    return set(get_registration(index_type).filterable_attributes)


def default_facet_attributes(index_type: IndexType) -> list[str]:
    return list(get_registration(index_type).default_facet_attributes)


def normalize_filter_attribute(attr: str, index_type: IndexType) -> str:
    allowed = allowed_filter_attributes(index_type)
    if attr in allowed:
        return attr
    if attr.endswith("_exact"):
        base = attr[:-6]
        if base in allowed:
            return base
    return attr


def requested_facet_attributes(raw: str, index_type: IndexType) -> list[str]:
    allowed = allowed_filter_attributes(index_type)
    return [facet.strip() for facet in raw.split(",") if facet.strip() and facet.strip() in allowed]


def sanitize_filter_spec(spec: FilterSpec, index_type: IndexType) -> FilterSpec:
    """Drop disallowed filter attributes in one place."""
    allowed = allowed_filter_attributes(index_type)
    return FilterSpec(
        equal={attr: value for attr, value in spec.equal.items() if attr in allowed},
        not_equal={attr: value for attr, value in spec.not_equal.items() if attr in allowed},
        in_={attr: values for attr, values in spec.in_.items() if attr in allowed},
        range_={attr: value_range for attr, value_range in spec.range_.items() if attr in allowed},
        min_date=spec.min_date,
        max_date=spec.max_date,
        at_most_or_least=spec.at_most_or_least,
        date_diff=spec.date_diff,
    )

"""Parse request query params into SearchQuery, FilterSpec, SortSpec."""

from apps.search.meilisearch.config import DEFAULT_FACET_ATTRIBUTES, FILTERABLE_ATTRIBUTES, SORTABLE_ATTRIBUTES
from apps.search.types import FilterSpec, IndexType, SearchQuery, SortSpec


def parse_search_query(
    query_params: dict,
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
    limit = _int_param(query_params.get("limit"), default_limit, 1, max_limit)
    offset = _int_param(query_params.get("offset"), 0, 0, None)

    filter_spec = _parse_filter_spec(query_params, index_type)
    sort_spec = _parse_sort_spec(query_params, index_type)

    return SearchQuery(
        q=q,
        filter_spec=filter_spec,
        sort_spec=sort_spec,
        limit=limit,
        offset=offset,
    )


def _normalize_facet_attr(attr: str, index_type: IndexType) -> str:
    """Map frontend facet key to Meilisearch filterable attribute.
    Frontend sends e.g. image_availability_exact; index has image_availability."""
    allowed = set(FILTERABLE_ATTRIBUTES.get(index_type, []))
    if attr in allowed:
        return attr
    if attr.endswith("_exact"):
        base = attr[:-6]  # strip _exact
        if base in allowed:
            return base
    return attr


def _parse_filter_spec(query_params: dict, index_type: IndexType) -> FilterSpec:
    """Build FilterSpec from query params. All params except q, sort, limit, offset are treated as filters.
    Also supports selected_facets (multi-value) with entries like 'attr_exact:value' or 'attr:value'."""
    reserved = {"q", "sort", "ordering", "limit", "offset", "facets", "page", "page_size"}
    equal = {}
    not_equal = {}
    in_ = {}
    range_ = {}

    # Parse selected_facets (frontend sends e.g. image_availability_exact:With images)
    if hasattr(query_params, "getlist"):
        for entry in query_params.getlist("selected_facets") or []:
            entry = (entry or "").strip()
            if not entry:
                continue
            if ":" in entry:
                attr, _, val = entry.partition(":")
                attr, val = attr.strip(), val.strip()
                if attr and val:
                    equal[_normalize_facet_attr(attr, index_type)] = val
    elif isinstance(query_params.get("selected_facets"), list):
        for entry in query_params.get("selected_facets") or []:
            entry = (str(entry or "").strip())
            if ":" in entry:
                attr, _, val = entry.partition(":")
                attr, val = attr.strip(), val.strip()
                if attr and val:
                    equal[_normalize_facet_attr(attr, index_type)] = val

    for key in query_params:
        if key in reserved or key == "selected_facets":
            continue
        if hasattr(query_params, "getlist"):
            values = [str(v).strip() for v in query_params.getlist(key) if v and str(v).strip()]
        else:
            v = query_params.get(key)
            values = [str(v).strip()] if v and str(v).strip() else []
        if not values:
            continue
        if key.endswith("__not"):
            attr = key[:-5]
            not_equal[attr] = values[0]
        elif len(values) == 1:
            equal[key] = values[0]
        else:
            equal[key] = values

    min_date = _int_param(query_params.get("min_date"))
    max_date = _int_param(query_params.get("max_date"))
    at_most_or_least = (query_params.get("at_most_or_least") or "").strip() or None
    date_diff = _int_param(query_params.get("date_diff"))

    return FilterSpec(
        equal=equal,
        not_equal=not_equal,
        in_=in_,
        range_=range_,
        min_date=min_date,
        max_date=max_date,
        at_most_or_least=at_most_or_least,
        date_diff=date_diff,
    )


def _parse_sort_spec(query_params: dict, index_type: IndexType) -> SortSpec | None:
    """Parse sort param: 'attribute:asc', 'attribute:desc', '-attribute'. Accepts 'ordering' as alias for 'sort'."""
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


def _int_param(value, default=None, min_val=None, max_val=None) -> int | None:
    """Parse an int from query param."""
    if value is None or value == "":
        return default
    try:
        n = int(value)
        if min_val is not None and n < min_val:
            n = min_val
        if max_val is not None and n > max_val:
            n = max_val
        return n
    except (TypeError, ValueError):
        return default


def parse_facet_attributes(query_params: dict, index_type: IndexType) -> list[str]:
    """Parse facets param (comma-separated) or return default for index type."""
    facets_param = (query_params.get("facets") or "").strip()
    if facets_param:
        return [f.strip() for f in facets_param.split(",") if f.strip()]
    return DEFAULT_FACET_ATTRIBUTES.get(index_type, [])

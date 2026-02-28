from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.parsers import parse_facet_attributes, parse_search_query
from apps.search.types import FilterSpec, IndexType


def test_parse_facet_attributes_enforces_allowlist():
    params = {"facets": "type,repository_name,not_allowed"}
    facets = parse_facet_attributes(params, IndexType.ITEM_PARTS)
    assert facets == ["type", "repository_name"]


def test_parse_selected_facets_ignores_unknown_attributes():
    params = {"selected_facets": ["type:charter", "unknown:value"]}
    query = parse_search_query(params, IndexType.ITEM_PARTS)
    assert query.filter_spec.equal == {"type": "charter"}


def test_meilisearch_filter_ignores_disallowed_fields():
    spec = FilterSpec(equal={"type": "charter", "unknown": "x"})
    expr = build_meilisearch_filter(spec, IndexType.ITEM_PARTS)
    assert expr == 'type = "charter"'

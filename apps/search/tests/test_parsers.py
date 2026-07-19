import pytest

from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.parsers import _parse_sort_spec, parse_facet_attributes, parse_search_query
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


@pytest.mark.parametrize(
    ("raw", "attribute", "ascending"),
    [
        ("shelfmark", "shelfmark", True),
        ("-shelfmark", "shelfmark", False),
        ("shelfmark:asc", "shelfmark", True),
        ("shelfmark:desc", "shelfmark", False),
        ("-date_min", "date_min", False),
    ],
)
def test_parse_sort_spec_reads_direction(raw, attribute, ascending):
    spec = _parse_sort_spec({"sort": raw}, IndexType.ITEM_PARTS)
    assert spec is not None
    assert spec.attribute == attribute
    assert spec.ascending is ascending


def test_parse_sort_spec_strips_exact_suffix():
    """The frontend mirrors the filter convention and appends `_exact`."""
    spec = _parse_sort_spec({"sort": "-repository_name_exact"}, IndexType.ITEM_PARTS)
    assert spec is not None
    assert spec.attribute == "repository_name"
    assert spec.ascending is False


@pytest.mark.parametrize("param", ["sort", "ordering"])
def test_parse_sort_spec_honours_both_param_names(param):
    spec = _parse_sort_spec({param: "-date_max"}, IndexType.ITEM_PARTS)
    assert spec is not None
    assert spec.attribute == "date_max"
    assert spec.ascending is False


@pytest.mark.parametrize("raw", ["", "not_sortable", "-not_sortable", "content:desc"])
def test_parse_sort_spec_drops_non_allowlisted_attributes(raw):
    """Unknown attributes are silently dropped rather than 400-ing."""
    assert _parse_sort_spec({"sort": raw}, IndexType.ITEM_PARTS) is None


def test_parse_sort_spec_allows_newly_unlocked_graph_attributes():
    """Regression net for issue #67: these graph sorts were rejected before."""
    for attribute in ("character", "character_type", "hand_name", "scribe", "locus", "type", "date_min"):
        spec = _parse_sort_spec({"ordering": attribute}, IndexType.GRAPHS)
        assert spec is not None, f"{attribute} should be sortable on the graphs index"
        assert spec.attribute == attribute


@pytest.mark.parametrize(
    ("index_type", "attribute"),
    [
        (IndexType.ITEM_PARTS, "format"),
        (IndexType.TEXTS, "status"),
        (IndexType.TEXTS, "language"),
        (IndexType.CLAUSES, "status"),
        (IndexType.PEOPLE, "status"),
        (IndexType.PLACES, "status"),
    ],
)
def test_parse_sort_spec_allows_status_format_language_columns(index_type, attribute):
    """Issue #67 follow-up: these columns render a sort button in results-table.tsx.

    The frontend sends the `_exact` suffix, so exercise that exact wire form —
    before the fix the attribute was missing from `sortable_attributes` and the
    sort was silently dropped (None), leaving the header button inert.
    """
    for raw, ascending in ((f"{attribute}_exact", True), (f"-{attribute}_exact", False)):
        spec = _parse_sort_spec({"ordering": raw}, index_type)
        assert spec is not None, f"{raw} should be sortable on the {index_type.value} index"
        assert spec.attribute == attribute
        assert spec.ascending is ascending

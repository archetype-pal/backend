import pytest

from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.parsers import parse_facet_attributes, parse_search_query
from apps.search.types import IndexType


def test_parse_facet_attributes_enforces_allowlist():
    params = {"facets": "type,repository_name,not_allowed"}
    facets = parse_facet_attributes(params, IndexType.ITEM_PARTS)
    assert facets == ["type", "repository_name"]


def test_parse_selected_facets_ignores_unknown_attributes():
    params = {"selected_facets": ["type:charter", "unknown:value"]}
    query = parse_search_query(params, IndexType.ITEM_PARTS)
    assert query.filter_spec.equal == {"type": "charter"}


def test_meilisearch_filter_ignores_disallowed_fields():
    # Sanitisation happens once, in the parser; the compiled filter must only name filterable fields.
    query = parse_search_query({"type": "charter", "unknown": "x"}, IndexType.ITEM_PARTS)
    assert build_meilisearch_filter(query.filter_spec) == 'type = "charter"'


_DATE_WINDOW = {"min_date": "1100", "max_date": "1200", "at_most_or_least": "at most", "date_diff": "25"}


def test_meilisearch_filter_keeps_date_range_on_dated_indexes():
    query = parse_search_query(_DATE_WINDOW, IndexType.ITEM_PARTS)
    assert build_meilisearch_filter(query.filter_spec) == "date_min >= 1100 AND date_max <= 1200 AND date_max <= 1125"


@pytest.mark.parametrize("index_type", [IndexType.HANDS, IndexType.ITEM_IMAGES])
def test_meilisearch_filter_keeps_date_range_on_images_and_hands(index_type):
    # Images and hands carry the numeric bounds too, so the date window reaches them.
    query = parse_search_query(_DATE_WINDOW, index_type)
    assert build_meilisearch_filter(query.filter_spec) == "date_min >= 1100 AND date_max <= 1200 AND date_max <= 1125"


@pytest.mark.parametrize("index_type", [IndexType.SCRIBES])
def test_meilisearch_filter_drops_date_range_on_undated_indexes(index_type):
    # Meilisearch rejects a clause on a field that isn't filterable, which surfaced as a 500.
    query = parse_search_query(_DATE_WINDOW, index_type)
    assert build_meilisearch_filter(query.filter_spec) is None


@pytest.mark.parametrize(
    ("raw", "offset"),
    [("40", 40), ("-5", 0), ("abc", 0), ("1000000", 1_000_000), (str(2**64), 1_000_000)],
)
def test_parse_search_query_keeps_the_offset_within_the_reachable_hits(raw, offset):
    # No hit lies past the indexes' maxTotalHits (1,000,000).
    assert parse_search_query({"offset": raw}, IndexType.SCRIBES).offset == offset


def _sort(params, index_type=IndexType.ITEM_PARTS):
    spec = parse_search_query(params, index_type).sort_spec
    return None if spec is None else (spec.attribute, spec.ascending)


@pytest.mark.parametrize(
    ("index_type", "cropped"),
    [(IndexType.TEXTS, ["content"]), (IndexType.CLAUSES, []), (IndexType.ITEM_PARTS, [])],
)
def test_only_the_texts_list_crops_its_content(index_type, cropped):
    # A clause card shows its whole content, so only the texts index — whose list shows a
    # snippet of the transcription — asks Meilisearch to crop.
    query = parse_search_query({}, index_type)
    assert query.attributes_to_crop == cropped
    assert (query.crop_length is not None) == bool(cropped)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"sort": "shelfmark"}, ("shelfmark", True)),
        ({"sort": "-shelfmark"}, ("shelfmark", False)),
        ({"sort": "shelfmark:asc"}, ("shelfmark", True)),
        ({"sort": "shelfmark:desc"}, ("shelfmark", False)),
        ({"ordering": "-date_max"}, ("date_max", False)),  # both parameter names are honoured
        ({"sort": "-repository_name_exact"}, ("repository_name", False)),  # the frontend's filter suffix
        # Unknown attributes are silently dropped rather than 400-ing.
        ({"sort": ""}, None),
        ({"sort": "not_sortable"}, None),
        ({"sort": "-not_sortable"}, None),
        ({"sort": "content:desc"}, None),
    ],
)
def test_sort_parsing(params, expected):
    assert _sort(params) == expected


@pytest.mark.parametrize(
    ("index_type", "attribute"),
    [
        # Every column that renders a sort button in the frontend's results table (#67).
        *[(IndexType.GRAPHS, a) for a in ("character", "character_type", "hand_name", "scribe", "locus", "type")],
        (IndexType.ITEM_PARTS, "format"),
        (IndexType.TEXTS, "status"),
        (IndexType.TEXTS, "language"),
        (IndexType.CLAUSES, "status"),
        (IndexType.PEOPLE, "status"),
        (IndexType.PLACES, "status"),
    ],
)
def test_every_column_with_a_sort_button_is_sortable(index_type, attribute):
    assert _sort({"ordering": f"-{attribute}_exact"}, index_type) == (attribute, False)

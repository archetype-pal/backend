"""Tests for the shared Meilisearch filter-value escaping (the injection boundary).

`escape_filter_value` is the single helper used by both the FilterSpec builder
and the query-builder parser, so an embedded quote can never break out of a
quoted filter literal. Pure unit tests: no DB or Meilisearch.
"""

from apps.search.filter_contract import escape_filter_value
from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.types import FilterSpec, IndexType


def test_escape_filter_value_wraps_strings_in_quotes():
    assert escape_filter_value("plain") == '"plain"'


def test_escape_filter_value_escapes_embedded_quotes():
    assert escape_filter_value('a"b') == '"a\\"b"'


def test_escape_filter_value_passes_numbers_through_bare():
    assert escape_filter_value(5) == "5"
    assert escape_filter_value(3.5) == "3.5"


def test_build_filter_escapes_quote_bearing_equality_value():
    # A value carrying a quote + operator must be fully contained in the quoted
    # literal — it cannot inject a second clause.
    spec = FilterSpec(equal={"scriptorium": 'X" OR id = 1'})
    out = build_meilisearch_filter(spec, IndexType.SCRIBES)
    assert out == 'scriptorium = "X\\" OR id = 1"'

"""The shared Meilisearch filter-value escaping — the injection boundary.

`escape_filter_value` is used by both the FilterSpec builder and the
query-builder parser, so an embedded quote can never break out of a literal.
"""

import pytest

from apps.search.filter_contract import escape_filter_value
from apps.search.meilisearch.filters import build_meilisearch_filter
from apps.search.types import FilterSpec


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", '"plain"'),
        ('a"b', '"a\\"b"'),
        # A trailing backslash would otherwise escape the closing quote, and
        # Meilisearch reads `\\` back as one backslash.
        ("foo\\", '"foo\\\\"'),
        ('a\\"b', '"a\\\\\\"b"'),
        (5, "5"),
        (3.5, "3.5"),
    ],
)
def test_escape_filter_value(value, expected):
    assert escape_filter_value(value) == expected


def test_build_filter_escapes_quote_bearing_equality_value():
    # The quote+operator must stay inside the literal, not open a second clause.
    spec = FilterSpec(equal={"scriptorium": 'X" OR id = 1'})
    assert build_meilisearch_filter(spec) == 'scriptorium = "X\\" OR id = 1"'

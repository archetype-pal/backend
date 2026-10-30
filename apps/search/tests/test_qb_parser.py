"""Unit tests for the query-builder (`qb`) parser.

`parse_qb_param` decodes user-supplied base64url JSON into a `FilterSpec` whose
`qb_expr` is interpolated *raw* into the Meilisearch filter string, so these pin
the two guards on that path — the field allowlist and the value escaping — plus
group precedence and malformed input.
"""

import base64
import json

import pytest

from apps.search.qb_parser import parse_qb_param
from apps.search.types import IndexType

# SCRIBES filterable_attributes = ["id", "name", "period", "scriptorium"].
INDEX = IndexType.SCRIBES


def _qb(node: object) -> str:
    """Encode a query-builder tree the way the frontend does (base64url, unpadded)."""
    raw = json.dumps(node).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cond(field, op, value=None, value_to=None) -> dict:
    node = {"t": "cond", "field": field, "op": op}
    if value is not None:
        node["value"] = value
    if value_to is not None:
        node["valueTo"] = value_to
    return node


def _group(op, *items) -> dict:
    return {"t": "group", "op": op, "items": list(items)}


@pytest.mark.parametrize(
    ("tree", "expr"),
    [
        # Only allow-listed fields survive; the frontend's `_exact` suffix is normalised.
        (_group("AND", _cond("evil", "is", "x"), _cond("scriptorium", "is", "Y")), 'scriptorium = "Y"'),
        (_cond("scriptorium_exact", "is", "Y"), 'scriptorium = "Y"'),
        # Values are escaped, never interpolated raw.
        (_cond("scriptorium", "is", 'va"lue'), 'scriptorium = "va\\"lue"'),
        (_cond("scriptorium", "is_not", "Y"), 'scriptorium != "Y"'),
        (_cond("scriptorium", "is_empty"), "scriptorium IS NULL"),
        (_cond("scriptorium", "is_not_empty"), "scriptorium IS NOT NULL"),
        # `gte` / `lte` are the names for what these compile to; `gt` / `lt` are kept as aliases.
        (_cond("id", "gte", "5"), "id >= 5.0"),
        (_cond("id", "lte", "9"), "id <= 9.0"),
        (_cond("id", "gt", "5"), "id >= 5.0"),
        (_cond("id", "lt", "9"), "id <= 9.0"),
        (_cond("id", "between", "1", "10"), "(id >= 1.0 AND id <= 10.0)"),
        (_group("AND", _cond("scriptorium", "is", "A"), _cond("name", "is", "B")), 'scriptorium = "A" AND name = "B"'),
        (_group("OR", _cond("scriptorium", "is", "A"), _cond("name", "is", "B")), '(scriptorium = "A" OR name = "B")'),
        # An OR branch stays parenthesised inside an AND so precedence holds.
        (
            _group(
                "AND", _cond("scriptorium", "is", "A"), _group("OR", _cond("name", "is", "B"), _cond("name", "is", "C"))
            ),
            'scriptorium = "A" AND ((name = "B" OR name = "C"))',
        ),
    ],
)
def test_trees_compile_to_escaped_filter_expressions(tree, expr):
    spec = parse_qb_param(_qb(tree), INDEX)
    assert spec is not None
    assert spec.qb_expr == expr


def test_text_operators_become_full_text_constraints_not_filter_expressions():
    contains = parse_qb_param(_qb(_cond("scriptorium", "contains", "foo")), INDEX)
    assert (contains.qb_expr, contains.contains) == (None, {"scriptorium": "foo"})
    assert parse_qb_param(_qb(_cond("scriptorium", "starts_with", "foo")), INDEX).starts_with == {"scriptorium": "foo"}


@pytest.mark.parametrize(
    "encoded",
    [
        _qb(_cond("password", "is", "x")),  # unknown field
        _qb(_cond("id", "gt", "abc")),  # non-numeric value for a numeric operator
        _qb(_cond("id", "between", "1")),  # missing bound
        _qb(_group("AND")),
        _qb([1, 2, 3]),  # not an object
        _qb({"t": "wat", "field": "scriptorium"}),  # unknown node type
        "",
        "   ",
        "!!!not base64!!!",
        base64.urlsafe_b64encode(b"not json").decode().rstrip("="),
    ],
)
def test_malformed_or_empty_input_yields_no_spec(encoded):
    assert parse_qb_param(encoded, INDEX) is None

"""Unit tests for the query-builder (`qb`) parser.

`parse_qb_param` decodes a user-supplied base64url JSON tree into a `FilterSpec`
whose `qb_expr` is interpolated *raw* into the Meilisearch filter string
(`apps/search/meilisearch/filters.py`). These tests pin the two security-
relevant guards on that path — the `_filterable` field allowlist and the
`_escape_meili` value escaping — plus the AND/OR group precedence and the
malformed-input handling. Pure unit tests: no DB or Meilisearch required.
"""

import base64
import json

from apps.search.qb_parser import parse_qb_param
from apps.search.types import IndexType

# SCRIBES filterable_attributes = ["id", "name", "period", "scriptorium"].
INDEX = IndexType.SCRIBES


def _qb(node: dict) -> str:
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


# --------------------------------------------------------------------------
# Field allowlist (the injection boundary)
# --------------------------------------------------------------------------


def test_unknown_field_is_dropped_and_yields_no_spec():
    spec = parse_qb_param(_qb(_cond("password", "is", "x")), INDEX)
    assert spec is None


def test_unknown_field_inside_group_is_dropped():
    spec = parse_qb_param(_qb(_group("AND", _cond("evil", "is", "x"), _cond("scriptorium", "is", "Y"))), INDEX)
    # Only the allowlisted condition survives.
    assert spec is not None
    assert spec.qb_expr == 'scriptorium = "Y"'


def test_exact_suffixed_field_normalizes_to_base_attribute():
    spec = parse_qb_param(_qb(_cond("scriptorium_exact", "is", "Y")), INDEX)
    assert spec is not None
    assert spec.qb_expr == 'scriptorium = "Y"'


# --------------------------------------------------------------------------
# Value escaping
# --------------------------------------------------------------------------


def test_embedded_double_quotes_are_escaped():
    spec = parse_qb_param(_qb(_cond("scriptorium", "is", 'va"lue')), INDEX)
    assert spec is not None
    # The embedded quote must be backslash-escaped so it cannot break out of
    # the quoted Meilisearch literal.
    assert spec.qb_expr == 'scriptorium = "va\\"lue"'


def test_is_not_uses_inequality():
    spec = parse_qb_param(_qb(_cond("scriptorium", "is_not", "Y")), INDEX)
    assert spec is not None
    assert spec.qb_expr == 'scriptorium != "Y"'


def test_is_empty_and_is_not_empty():
    assert parse_qb_param(_qb(_cond("scriptorium", "is_empty")), INDEX).qb_expr == "scriptorium IS NULL"
    assert parse_qb_param(_qb(_cond("scriptorium", "is_not_empty")), INDEX).qb_expr == "scriptorium IS NOT NULL"


# --------------------------------------------------------------------------
# Numeric operators
# --------------------------------------------------------------------------


def test_gt_and_lt_coerce_numbers():
    assert parse_qb_param(_qb(_cond("id", "gt", "5")), INDEX).qb_expr == "id >= 5.0"
    assert parse_qb_param(_qb(_cond("id", "lt", "9")), INDEX).qb_expr == "id <= 9.0"


def test_between_emits_bounded_range():
    spec = parse_qb_param(_qb(_cond("id", "between", "1", "10")), INDEX)
    assert spec is not None
    assert spec.qb_expr == "(id >= 1.0 AND id <= 10.0)"


def test_non_numeric_value_for_numeric_op_is_dropped():
    # A non-numeric gt must NOT be interpolated as a string — the condition is
    # dropped entirely.
    spec = parse_qb_param(_qb(_cond("id", "gt", "abc")), INDEX)
    assert spec is None


def test_between_with_missing_bound_is_dropped():
    assert parse_qb_param(_qb(_cond("id", "between", "1")), INDEX) is None


# --------------------------------------------------------------------------
# contains / starts_with extraction
# --------------------------------------------------------------------------


def test_contains_populates_contains_not_qb_expr():
    spec = parse_qb_param(_qb(_cond("scriptorium", "contains", "foo")), INDEX)
    assert spec is not None
    assert spec.qb_expr is None
    assert spec.contains == {"scriptorium": "foo"}


def test_starts_with_populates_starts_with():
    spec = parse_qb_param(_qb(_cond("scriptorium", "starts_with", "foo")), INDEX)
    assert spec is not None
    assert spec.starts_with == {"scriptorium": "foo"}


# --------------------------------------------------------------------------
# Group precedence
# --------------------------------------------------------------------------


def test_and_group_joins_with_and():
    spec = parse_qb_param(_qb(_group("AND", _cond("scriptorium", "is", "A"), _cond("name", "is", "B"))), INDEX)
    assert spec is not None
    assert spec.qb_expr == 'scriptorium = "A" AND name = "B"'


def test_or_group_is_parenthesized():
    spec = parse_qb_param(_qb(_group("OR", _cond("scriptorium", "is", "A"), _cond("name", "is", "B"))), INDEX)
    assert spec is not None
    assert spec.qb_expr == '(scriptorium = "A" OR name = "B")'


def test_or_nested_in_and_is_wrapped_to_preserve_precedence():
    tree = _group(
        "AND",
        _cond("scriptorium", "is", "A"),
        _group("OR", _cond("name", "is", "B"), _cond("name", "is", "C")),
    )
    spec = parse_qb_param(_qb(tree), INDEX)
    assert spec is not None
    # The OR branch must stay parenthesized inside the AND so precedence holds.
    assert spec.qb_expr == 'scriptorium = "A" AND ((name = "B" OR name = "C"))'


def test_empty_group_yields_no_spec():
    assert parse_qb_param(_qb(_group("AND")), INDEX) is None


# --------------------------------------------------------------------------
# Malformed / hostile input
# --------------------------------------------------------------------------


def test_blank_input_returns_none():
    assert parse_qb_param("", INDEX) is None
    assert parse_qb_param("   ", INDEX) is None


def test_invalid_base64_returns_none():
    assert parse_qb_param("!!!not base64!!!", INDEX) is None


def test_non_json_payload_returns_none():
    assert parse_qb_param(base64.urlsafe_b64encode(b"not json").decode().rstrip("="), INDEX) is None


def test_non_object_json_returns_none():
    # A JSON array (not a dict) must be rejected before evaluation.
    assert parse_qb_param(_qb([1, 2, 3]), INDEX) is None


def test_unknown_node_type_returns_none():
    assert parse_qb_param(_qb({"t": "wat", "field": "scriptorium"}), INDEX) is None

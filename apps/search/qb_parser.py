"""Parse URL `qb` (base64url JSON) query-builder trees into FilterSpec fragments."""

from __future__ import annotations

import base64
import json
from typing import Any

from apps.search.filter_contract import allowed_filter_attributes, normalize_filter_attribute
from apps.search.types import FilterSpec, IndexType


def _b64url_decode(raw: str) -> bytes | None:
    s = raw.strip().replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    try:
        return base64.b64decode(s, validate=True)
    except (ValueError, TypeError):  # fmt: skip
        return None


def _escape_meili(value: object) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace('"', '\\"')
    return f'"{s}"'


def parse_qb_param(raw: str, index_type: IndexType) -> FilterSpec | None:
    """Decode qb param and return FilterSpec (qb_expr + contains + starts_with)."""
    if not raw or not raw.strip():
        return None
    blob = _b64url_decode(raw)
    if not blob:
        return None
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):  # fmt: skip
        return None
    if not isinstance(data, dict):
        return None
    expr, contains, starts_with = _eval_node(data, index_type)
    if expr is None and not contains and not starts_with:
        return None
    return FilterSpec(qb_expr=expr, contains=contains, starts_with=starts_with)


def _filterable(field: str, index_type: IndexType) -> str | None:
    normalized = normalize_filter_attribute(field, index_type)
    if normalized in allowed_filter_attributes(index_type):
        return normalized
    return None


def _parse_number(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _eval_cond(node: dict[str, Any], index_type: IndexType) -> tuple[str | None, dict[str, str], dict[str, str]]:
    field_raw = str(node.get("field") or "").strip()
    op = str(node.get("op") or "is").lower()
    value = node.get("value")
    value_to = node.get("valueTo")
    val_s = "" if value is None else str(value).strip()
    val_to_s = "" if value_to is None else str(value_to).strip()
    contains: dict[str, str] = {}
    starts_with: dict[str, str] = {}

    if op == "contains":
        f = _filterable(field_raw, index_type)
        if f:
            contains[f] = val_s
        return None, contains, starts_with
    if op == "starts_with":
        f = _filterable(field_raw, index_type)
        if f:
            starts_with[f] = val_s
        return None, contains, starts_with

    field = _filterable(field_raw, index_type)
    if not field:
        return None, contains, starts_with

    if op == "is_empty":
        return f"{field} IS NULL", contains, starts_with
    if op == "is_not_empty":
        return f"{field} IS NOT NULL", contains, starts_with
    if op == "is":
        return f"{field} = {_escape_meili(val_s)}", contains, starts_with
    if op == "is_not":
        return f"{field} != {_escape_meili(val_s)}", contains, starts_with
    if op == "gt":
        num = _parse_number(val_s)
        if num is None:
            return None, contains, starts_with
        return f"{field} >= {num}", contains, starts_with
    if op == "lt":
        num = _parse_number(val_s)
        if num is None:
            return None, contains, starts_with
        return f"{field} <= {num}", contains, starts_with
    if op == "between":
        lo = _parse_number(val_s)
        hi = _parse_number(val_to_s)
        if lo is None or hi is None:
            return None, contains, starts_with
        return f"({field} >= {lo} AND {field} <= {hi})", contains, starts_with
    return None, contains, starts_with


def _eval_node(node: dict[str, Any], index_type: IndexType) -> tuple[str | None, dict[str, str], dict[str, str]]:
    t = node.get("t")
    if t == "cond":
        return _eval_cond(node, index_type)
    if t != "group":
        return None, {}, {}

    op = str(node.get("op") or "AND").upper()
    items = node.get("items")
    if not isinstance(items, list) or not items:
        return None, {}, {}

    child_results = []
    for item in items:
        if isinstance(item, dict):
            child_results.append(_eval_node(item, index_type))

    merged_contains: dict[str, str] = {}
    merged_starts: dict[str, str] = {}
    for _, c, s in child_results:
        merged_contains.update(c)
        merged_starts.update(s)

    filter_parts = [e for e, _, _ in child_results if e]
    if not filter_parts:
        return None, merged_contains, merged_starts
    if op == "OR":
        expr = "(" + " OR ".join(filter_parts) + ")"
    else:
        expr = " AND ".join(f"({p})" if " OR " in p else p for p in filter_parts)
    return expr, merged_contains, merged_starts

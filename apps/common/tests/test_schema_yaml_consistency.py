"""Structural consistency checks across all per-app schema.yaml files (ROADMAP 4.2).

The project rejects code-introspection schema generators (drf-spectacular et al.)
and ships per-app schema.yaml files hand-authored by humans. That's a sustainable
choice only with a few cheap automated guards so the YAML can't silently drift.

This test file owns the cheap structural ones:
- no duplicate operationIds within a file (the failure mode that produced earlier
  bugs like item-part-images-list being attached to both list and detail);
- no two files claim the same path with conflicting operationIds.

Semantic drift (a path's request/response shape diverging from the viewset) still
needs a hand-audit when serializers change. Reviewers should treat "viewset /
serializer changed but schema.yaml did not" as a review block.
"""

from collections import Counter
from pathlib import Path

import yaml

APPS_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA_FILES = sorted(APPS_DIR.glob("*/schema.yaml"))


def _load_schema(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def test_schema_files_discoverable():
    """Smoke check — the audit only works if we found schema files."""
    assert SCHEMA_FILES, "No apps/*/schema.yaml found — schema audit cannot run"
    assert len(SCHEMA_FILES) >= 7, f"Expected at least 7 schema files, got {len(SCHEMA_FILES)}"


def test_no_duplicate_operation_ids_within_each_file():
    """Each schema.yaml may use any operationId once. Duplicates cause client
    code generators to collide; the previously-shipped item-part-images-list
    duplicate was the failure mode that motivated this check."""
    offenders: dict[str, list[str]] = {}
    for path in SCHEMA_FILES:
        schema = _load_schema(path)
        op_ids: list[str] = []
        for _path_str, operations in (schema.get("paths") or {}).items():
            if not isinstance(operations, dict):
                continue
            for _method, operation in operations.items():
                if not isinstance(operation, dict):
                    continue
                op_id = operation.get("operationId")
                if op_id:
                    op_ids.append(op_id)
        dups = [op for op, count in Counter(op_ids).items() if count > 1]
        if dups:
            offenders[str(path)] = dups
    assert not offenders, f"Duplicate operationIds detected: {offenders}"


def test_no_two_files_register_the_same_path_with_conflicting_operations():
    """If two apps claim the same path for the same method, the operationId must
    match. Mismatched duplicates create non-deterministic client behaviour."""
    seen: dict[tuple[str, str], tuple[str, Path]] = {}
    conflicts: list[str] = []
    for path in SCHEMA_FILES:
        schema = _load_schema(path)
        for path_str, operations in (schema.get("paths") or {}).items():
            if not isinstance(operations, dict):
                continue
            for method, operation in operations.items():
                if not isinstance(operation, dict):
                    continue
                op_id = operation.get("operationId", "")
                key = (path_str, method.lower())
                if key in seen:
                    prev_op_id, prev_path = seen[key]
                    if prev_op_id != op_id:
                        conflicts.append(
                            f"{path_str} [{method}] declared in {prev_path} (op={prev_op_id}) and {path} (op={op_id})"
                        )
                else:
                    seen[key] = (op_id, path)
    assert not conflicts, "Cross-file path conflicts:\n" + "\n".join(conflicts)


def test_every_operation_has_an_operation_id():
    """A missing operationId is a generator hazard — every path×method must
    declare one so the consumer can name the call site."""
    missing: list[str] = []
    for path in SCHEMA_FILES:
        schema = _load_schema(path)
        for path_str, operations in (schema.get("paths") or {}).items():
            if not isinstance(operations, dict):
                continue
            for method, operation in operations.items():
                if not isinstance(operation, dict):
                    continue
                if not operation.get("operationId"):
                    missing.append(f"{path}: {path_str} [{method}]")
    assert not missing, "Operations without operationId:\n" + "\n".join(missing)

#!/usr/bin/env python3
"""Check that inter-app imports respect the dependency graph.

Allowed dependency graph (non-test code):
  common            → (nothing)
  manuscripts       → common, annotations
  symbols_structure → common
  scribes           → common, manuscripts, symbols_structure
  annotations       → common, symbols_structure
  annotations_w3c   → common, annotations, manuscripts
  iiif_presentation → common, annotations, manuscripts
  publications      → common, users
  worksets          → common, users
  users             → common
  search            → common, manuscripts, scribes, symbols_structure, annotations, publications
  uploads           → common, manuscripts, search

Every Django app under apps/ (a directory containing apps.py) must have an
entry here; the checker fails on any app that doesn't, so a new app can't
silently bypass the dependency policy.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

APPS_DIR = Path(__file__).resolve().parent.parent / "apps"

ALLOWED_DEPS: dict[str, set[str]] = {
    "common": set(),
    "manuscripts": {"common", "annotations"},
    "symbols_structure": {"common"},
    "scribes": {"common", "manuscripts", "symbols_structure"},
    "annotations": {"common", "symbols_structure"},
    "annotations_w3c": {"common", "annotations", "manuscripts"},
    "iiif_presentation": {"common", "annotations", "manuscripts"},
    "publications": {"common", "users"},
    "worksets": {"common", "users"},
    "users": {"common"},
    "search": {"common", "manuscripts", "scribes", "symbols_structure", "annotations", "publications"},
    "uploads": {"common", "manuscripts", "search"},
}

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+apps\.(\w+)")


def _undeclared_apps() -> list[str]:
    """Apps under apps/ (have apps.py) but missing from ALLOWED_DEPS."""
    missing: list[str] = []
    for app_dir in sorted(APPS_DIR.iterdir()):
        if not app_dir.is_dir() or not (app_dir / "apps.py").is_file():
            continue
        if app_dir.name not in ALLOWED_DEPS:
            missing.append(app_dir.name)
    return missing


def check_boundaries() -> list[str]:
    violations: list[str] = []
    for app_name in _undeclared_apps():
        violations.append(
            f"apps/{app_name}: no entry in ALLOWED_DEPS — declare its allowed dependencies "
            f"in scripts/check_architecture_boundaries.py"
        )
    for app_name, allowed in ALLOWED_DEPS.items():
        app_dir = APPS_DIR / app_name
        if not app_dir.is_dir():
            continue
        for py_file in app_dir.rglob("*.py"):
            # Skip tests and migrations
            rel = py_file.relative_to(app_dir)
            if rel.parts[0] in ("tests", "migrations"):
                continue
            for lineno, line in enumerate(py_file.read_text().splitlines(), 1):
                m = IMPORT_RE.match(line)
                if not m:
                    continue
                imported_app = m.group(1)
                if imported_app == app_name:
                    continue  # self-imports are fine
                if imported_app not in allowed:
                    violations.append(
                        f"{py_file.relative_to(APPS_DIR.parent)}:{lineno}: "
                        f"'{app_name}' imports from '{imported_app}' (not in allowed deps: {sorted(allowed)})"
                    )
    return violations


def main() -> int:
    violations = check_boundaries()
    if violations:
        print(f"Architecture boundary violations ({len(violations)}):\n")
        for v in violations:
            print(f"  {v}")
        return 1
    print("All architecture boundaries respected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

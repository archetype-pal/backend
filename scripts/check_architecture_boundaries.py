#!/usr/bin/env python3
"""Check that inter-app imports respect the dependency graph.

Allowed dependency graph (non-test code):
  common          → (nothing)
  manuscripts     → common
  symbols_structure → common
  scribes         → common, manuscripts, symbols_structure
  annotations     → common, symbols_structure
  publications    → common, users
  users           → common
  search          → common, manuscripts, scribes, symbols_structure, annotations, publications
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
    "publications": {"common", "users"},
    "users": {"common"},
    "search": {"common", "manuscripts", "scribes", "symbols_structure", "annotations", "publications"},
}

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+apps\.(\w+)")


def check_boundaries() -> list[str]:
    violations: list[str] = []
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

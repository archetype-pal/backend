#!/usr/bin/env python3
"""Check that inter-app imports respect the dependency graph.

Allowed dependency graph (non-test code):
  common               → (nothing)
  manuscripts          → common, annotations
  symbols_structure    → common
  scribes              → common, symbols_structure
  annotations          → common
  annotation_standards → common, annotations, manuscripts
  publications         → common
  pages                → common
  worksets             → common
  users                → common
  search               → common, manuscripts, scribes, symbols_structure, annotations
  uploads              → common, manuscripts

Every Django app under apps/ (a directory containing apps.py) must have an
entry here; the checker fails on any app that doesn't, so a new app can't
silently bypass the dependency policy.

Not visible to this check, and accepted: reverse ORM accessors. `scribes`
walks `hand.graph_set` to derive a scribe's idiographs, which is a use of the
`annotations` schema without an import; the FK (`Graph.hand`) is the
dependency the graph above records.

`common` additionally may not import `config` at module level: it is the
dependency-free foundation app and `config` is the composition root above it.
Function-local `config` imports are allowed.

Within an app, `services/`, `serializers/`, `models`, `signals` and `filters`
may not import from `views`: views are the transport layer on top of them.
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
    "scribes": {"common", "symbols_structure"},
    # Graph's allograph/component/position FKs are declared by label; no code import needed.
    "annotations": {"common"},
    # IIIF Presentation + W3C Web Annotation: the publication layer above both
    # the manuscript structure it serialises and the annotations it embeds.
    "annotation_standards": {"common", "annotations", "manuscripts"},
    "publications": {"common"},
    "pages": {"common"},
    "worksets": {"common"},
    "users": {"common"},
    "search": {"common", "manuscripts", "scribes", "symbols_structure", "annotations"},
    "uploads": {"common", "manuscripts"},
}

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+apps\.(\w+)")
# No leading whitespace — an indented `config` import is function-local, which is
# how the foundation app is allowed to reach it.
MODULE_LEVEL_CONFIG_IMPORT_RE = re.compile(r"^(?:from|import)\s+config\b")
CONFIG_FREE_APPS = {"common"}
# Modules below the view layer; a `views` import from any of them is a layering inversion.
BELOW_VIEWS = ("services", "serializers", "models", "signals", "filters")
VIEWS_IMPORT_RE = re.compile(r"^\s*from\s+(?:apps\.\w+\.views|\.views|\.\.views)\b|^\s*from\s+\.+\s+import\s+views\b")


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
    violations: list[str] = [
        f"apps/{app_name}: no entry in ALLOWED_DEPS — declare its allowed dependencies "
        f"in scripts/check_architecture_boundaries.py"
        for app_name in _undeclared_apps()
    ]
    for app_name, allowed in ALLOWED_DEPS.items():
        app_dir = APPS_DIR / app_name
        if not app_dir.is_dir():
            continue
        for py_file in app_dir.rglob("*.py"):
            # Skip tests and migrations
            rel = py_file.relative_to(app_dir)
            if rel.parts[0] in ("tests", "migrations"):
                continue
            below_views = rel.parts[0].removesuffix(".py") in BELOW_VIEWS
            for lineno, line in enumerate(py_file.read_text().splitlines(), 1):
                if below_views and VIEWS_IMPORT_RE.match(line):
                    violations.append(
                        f"{py_file.relative_to(APPS_DIR.parent)}:{lineno}: "
                        f"'{rel.parts[0]}' imports from a views module — views sit on top of it, not under it"
                    )
                if app_name in CONFIG_FREE_APPS and MODULE_LEVEL_CONFIG_IMPORT_RE.match(line):
                    violations.append(
                        f"{py_file.relative_to(APPS_DIR.parent)}:{lineno}: "
                        f"'{app_name}' imports 'config' at module level — the foundation app sits "
                        f"below the composition root; keep it function-local"
                    )
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

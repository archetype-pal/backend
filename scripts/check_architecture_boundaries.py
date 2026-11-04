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
  search               → common, manuscripts, scribes, symbols_structure, annotations, diplomatic, vision
  uploads              → common, manuscripts
  ml                   → common
  datasets             → common, manuscripts, scribes, symbols_structure, annotations
  diplomatic           → common, ml, manuscripts, scribes
  vision               → common, ml, manuscripts, annotations, scribes, symbols_structure
  agents               → common, ml, manuscripts, annotations, diplomatic

Every Django app under apps/ (a directory containing apps.py) must have an
entry here; the checker fails on any app that doesn't, so a new app can't
silently bypass the dependency policy.

Model relations are dependencies too, and imports cannot show them: Graph
declares its foreign keys by label. So the checker also derives, from Django's
model registry, every forward relation (foreign key, one-to-one, many-to-many)
from one app's models to another's, and requires it to match MODEL_RELATIONS:

  annotations → manuscripts, scribes, symbols_structure, ml
  manuscripts → common
  scribes     → common, manuscripts
  uploads     → manuscripts
  diplomatic  → manuscripts, ml

Imports and relations together must form no cycle, except through the edges in
MUTUAL_EDGES, each stated with the reason it is accepted. There is one:
manuscripts imports annotations while Graph relates to manuscripts' images.

Reverse ORM accessors stay invisible, and are accepted: `scribes` walks
`hand.graph_set` to derive a scribe's idiographs; the relation it rides on
(`Graph.hand`, annotations → scribes) is the one declared.

No app imports `config`: it is the composition root, above every app.

Within an app, `services/`, `serializers/`, `models`, `signals` and `filters`
may not import from `views`: views are the transport layer on top of them.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "apps"

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
    # `diplomatic` for the approved granters, beneficiaries and witnesses a text
    # document is faceted by. Read only: search writes no diplomatic row.
    # `vision` for each glyph's search vector, copied into its graph document.
    # Read only too, and one-way: vision announces new vectors by a signal, so
    # it never imports search.
    "search": {"common", "manuscripts", "scribes", "symbols_structure", "annotations", "diplomatic", "vision"},
    "uploads": {"common", "manuscripts"},
    # Deliberately minimal, and load-bearing: the inference ledger records the
    # records it touched as loose (target_type, target_id) pointers rather than
    # foreign keys, so `ml` never imports a domain app. That is what makes "no
    # edge from the inference service to the canonical record" a checked
    # property rather than a claim.
    "ml": {"common"},
    # Read-only: it publishes releases derived from the research data and
    # writes none of it.
    "datasets": {"common", "manuscripts", "scribes", "symbols_structure", "annotations"},
    # Phase 2. It reads charter texts and writes only its own tables, because
    # everything a model produces lands in its `Proposal` gate first; `ml` is
    # for the provenance FK, exactly as in `annotations`. It reads `scribes`
    # for the network's scribe attributions (W2.3), and writes nothing there.
    "diplomatic": {"common", "ml", "manuscripts", "scribes"},
    # Phase 1's vision items. It reaches further than any other AI app —
    # images, annotations, hands and the glyph taxonomy — because a glyph
    # proposal needs all four to be acceptable. It writes only draft texts and
    # `GraphProposal` rows; the promotion to a `Graph` is `annotations`' own,
    # and needs a named human.
    "vision": {"common", "ml", "manuscripts", "annotations", "scribes", "symbols_structure"},
    # Phase 3's public agent. It has the widest read surface in the codebase and
    # deliberately no write path: it may not import `scribes` or `search`, and
    # the tool allow-list narrows it much further again at runtime.
    "agents": {"common", "ml", "manuscripts", "annotations", "diplomatic"},
}

# Forward model relations between apps, derived from the models and checked against this.
MODEL_RELATIONS: dict[str, set[str]] = {
    # `ml` for the proposal gate's provenance FK: a machine-authored candidate
    # must stay attributable to the inference that produced it. The edge is
    # one-way (`ml` depends on `common` alone), so the inference side still
    # cannot reach the canonical record.
    "annotations": {"manuscripts", "scribes", "symbols_structure", "ml"},
    "manuscripts": {"common"},
    "scribes": {"common", "manuscripts"},
    "uploads": {"manuscripts"},
    # A proposal is about a charter text, and keeps the inference that produced it.
    "diplomatic": {"manuscripts", "ml"},
    # A glyph's vector belongs to the glyph, and keeps the inference that made it.
    # A hand's nearest hands (W1.3) belong to the hand.
    "vision": {"annotations", "ml", "scribes"},
}

# Edges that close a cycle in imports + relations, each with why it is accepted.
MUTUAL_EDGES: dict[tuple[str, str], str] = {
    ("manuscripts", "annotations"): (
        "A graph sits on an image (Graph.item_image), and the text and image services must see "
        "graphs: a text's TEI links its passages to its image's text regions, and an image carries "
        "its graphs when it moves or is deleted."
    ),
}

IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+apps\.(\w+)")
CONFIG_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+config\b")
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
                if CONFIG_IMPORT_RE.match(line):
                    violations.append(
                        f"{py_file.relative_to(APPS_DIR.parent)}:{lineno}: "
                        f"'{app_name}' imports 'config' — the composition root sits above every app"
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


def derived_relations() -> dict[str, set[str]]:
    """Every forward relation from one app's models to another app's, from Django's registry."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    # The registry is all this reads; no database is opened, so no server is needed.
    os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")
    import django
    from django.apps import apps

    django.setup()
    relations: dict[str, set[str]] = {}
    for config in apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        source = config.name.removeprefix("apps.")
        for model in config.get_models(include_auto_created=True):
            for field in model._meta.get_fields():
                if not (field.is_relation and field.concrete) or field.related_model is None:
                    continue
                target = apps.get_app_config(field.related_model._meta.app_label).name
                if target.startswith("apps.") and target.removeprefix("apps.") != source:
                    relations.setdefault(source, set()).add(target.removeprefix("apps."))
    return relations


def _cycle(edges: dict[str, set[str]]) -> list[str] | None:
    """One cycle in `edges`, as the path that closes it, or None."""
    state: dict[str, str] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = "open"
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            if state.get(nxt) == "open":
                return [*stack[stack.index(nxt) :], nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        stack.pop()
        state[node] = "done"
        return None

    for node in sorted(edges):
        if node not in state and (found := visit(node)):
            return found
    return None


def check_relations(relations: dict[str, set[str]]) -> list[str]:
    violations: list[str] = []
    for app_name in sorted(set(relations) | set(MODEL_RELATIONS)):
        found, declared = relations.get(app_name, set()), MODEL_RELATIONS.get(app_name, set())
        violations += [
            f"apps/{app_name}: its models relate to '{target}', which MODEL_RELATIONS does not declare"
            for target in sorted(found - declared)
        ]
        violations += [
            f"apps/{app_name}: MODEL_RELATIONS declares a relation to '{target}' that no model has"
            for target in sorted(declared - found)
        ]

    combined = {app: ALLOWED_DEPS.get(app, set()) | MODEL_RELATIONS.get(app, set()) for app in ALLOWED_DEPS}
    for source, target in MUTUAL_EDGES:
        if target not in combined.get(source, set()) or source not in combined.get(target, set()):
            violations.append(f"MUTUAL_EDGES: {source} → {target} no longer closes a cycle; drop it")
        combined[source] = combined.get(source, set()) - {target}
    if cycle := _cycle(combined):
        violations.append(
            f"imports and model relations form a cycle: {' → '.join(cycle)} "
            "(break it, or accept one edge in MUTUAL_EDGES with the reason)"
        )
    return violations


def main() -> int:
    violations = check_boundaries() + check_relations(derived_relations())
    if violations:
        print(f"Architecture boundary violations ({len(violations)}):\n")
        for v in violations:
            print(f"  {v}")
        return 1
    print("All architecture boundaries respected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

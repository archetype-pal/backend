"""The boundary checker's model-relation half: what it derives, and what it reports."""

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_architecture_boundaries.py"
_spec = importlib.util.spec_from_file_location("check_architecture_boundaries", _SCRIPT)
assert _spec and _spec.loader
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def test_the_declared_relations_are_the_models_relations():
    assert checker.derived_relations() == checker.MODEL_RELATIONS
    assert checker.check_relations(checker.derived_relations()) == []


def test_an_undeclared_relation_is_reported():
    relations = {**checker.MODEL_RELATIONS, "pages": {"manuscripts"}}

    assert checker.check_relations(relations) == [
        "apps/pages: its models relate to 'manuscripts', which MODEL_RELATIONS does not declare"
    ]


def test_a_declared_relation_no_model_has_is_reported():
    relations = {**checker.MODEL_RELATIONS, "uploads": set()}

    assert checker.check_relations(relations) == [
        "apps/uploads: MODEL_RELATIONS declares a relation to 'manuscripts' that no model has"
    ]


def test_a_cycle_outside_the_accepted_edge_is_reported(monkeypatch):
    monkeypatch.setattr(checker, "MUTUAL_EDGES", {})

    [violation] = checker.check_relations(checker.MODEL_RELATIONS)

    assert violation.startswith("imports and model relations form a cycle: annotations → manuscripts → annotations")


def test_an_accepted_edge_that_no_longer_closes_a_cycle_is_reported(monkeypatch):
    monkeypatch.setitem(checker.MODEL_RELATIONS, "annotations", {"scribes", "symbols_structure"})

    violations = checker.check_relations({**checker.MODEL_RELATIONS})

    assert "MUTUAL_EDGES: manuscripts → annotations no longer closes a cycle; drop it" in violations

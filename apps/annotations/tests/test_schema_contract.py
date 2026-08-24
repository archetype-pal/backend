"""Guard the hand-authored schema.yaml against the serializers it documents.

`apps/common/tests/test_schema_yaml_consistency.py` covers structure only, and
its docstring leaves semantic drift to a hand-audit. This closes that gap for
the two graph serializers a client generates types from: a field added to the
serializer but not to schema.yaml now fails here instead of shipping as a
silently under-documented response.
"""

from pathlib import Path

from django.conf import settings
import pytest
import yaml

from apps.annotations.serializers import GraphSerializer, GraphViewerWriteSerializer

SCHEMA_PATH = Path(settings.BASE_DIR) / "apps/annotations/schema.yaml"


def _documented_properties(component_name: str) -> set[str]:
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    component = schema["components"]["schemas"][component_name]
    return set(component.get("properties", {}))


@pytest.mark.parametrize(
    ("serializer_class", "component_name"),
    [
        (GraphSerializer, "Graph"),
        (GraphViewerWriteSerializer, "GraphViewerWrite"),
    ],
)
def test_every_serializer_field_is_documented(serializer_class, component_name):
    documented = _documented_properties(component_name)
    undocumented = sorted(set(serializer_class().fields) - documented)
    assert not undocumented, (
        f"{serializer_class.__name__} returns fields absent from components.schemas.{component_name}: {undocumented}"
    )

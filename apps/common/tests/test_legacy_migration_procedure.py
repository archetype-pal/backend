import json

from django.core.management import call_command

from apps.common.legacy_migration_procedure import (
    MIGRATION_PHASES,
    SAFETY_GATES,
    build_manifest_template,
    render_procedure_json,
    render_procedure_markdown,
)


def test_render_procedure_markdown_contains_safety_gates_and_phases():
    rendered = render_procedure_markdown()

    assert "# Legacy Migration Operator Guide" in rendered
    assert "Read-only audit gate" in rendered
    assert "`00_preflight` Preflight" in rendered
    assert "`08_annotations` Annotations And Graph Details" in rendered
    assert "Target-Only Current Data" in rendered
    assert "migrate_legacy_data" in rendered


def test_render_procedure_json_is_machine_readable():
    rendered = render_procedure_json()
    data = json.loads(rendered)

    assert data["procedure_version"] == "2026-05-29"
    assert data["phases"][0]["key"] == "00_preflight"
    assert any(gate["key"] == "audit_gate" for gate in data["safety_gates"])


def test_manifest_template_tracks_every_phase_and_gate_policy():
    template = build_manifest_template()
    phase_keys = [phase["key"] for phase in template["phases"]]

    assert phase_keys == [phase.key for phase in MIGRATION_PHASES]
    assert template["approval"]["allow_non_empty_target"] is False
    assert template["legacy"]["database_url_env"] == "LEGACY_DATABASE_URL"
    assert len(SAFETY_GATES) >= 8


def test_procedure_management_command_writes_guide_and_manifest(tmp_path):
    guide_path = tmp_path / "guide.md"
    manifest_path = tmp_path / "manifest.json"

    call_command(
        "legacy_migration_procedure",
        output=guide_path,
        manifest_template=manifest_path,
    )

    assert guide_path.read_text(encoding="utf-8").startswith("# Legacy Migration Operator Guide")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["phases"][0]["key"] == "00_preflight"

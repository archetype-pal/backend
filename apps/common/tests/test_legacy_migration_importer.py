import json

from django.core.management import call_command
import pytest

from apps.common.legacy_migration_importer import (
    ImportReport,
    LegacyMigrationImportError,
    PhaseResult,
    expand_phases,
    legacy_image_path,
    parse_annotation,
    parse_date_weights,
)


def test_expand_phases_defaults_to_full_order():
    phases = expand_phases(("all",))

    assert phases[0] == "core_vocabularies"
    assert phases[-1] == "target_only"
    assert "annotations" in phases


def test_expand_phases_rejects_mixed_all():
    with pytest.raises(LegacyMigrationImportError):
        expand_phases(("all", "manuscripts"))


def test_parse_date_weights_prefers_years_from_date_text():
    assert parse_date_weights("24 May 1153 X 1159") == (1153, 1159)
    assert parse_date_weights("X 8 March 1185") == (1185, 1185)


def test_parse_date_weights_falls_back_to_legacy_weights():
    assert parse_date_weights("", min_weight=1100, max_weight=1125, weight=None) == (1100, 1125)
    assert parse_date_weights(None, weight=1099) == (1099, 1099)
    assert parse_date_weights(None) == (0, 0)


def test_legacy_image_path_converts_iip_tif_paths():
    assert legacy_image_path("jp2/BLno1/path/k90069_51.tif") == "BLno1/path/k90069_51.jp2"
    assert legacy_image_path(None, "already.jp2") == "already.jp2"


def test_parse_annotation_accepts_legacy_python_dict_strings():
    assert parse_annotation("{'shapes': [{'type': 'rect'}]}") == {"shapes": [{"type": "rect"}]}
    assert parse_annotation("not parseable") == {"legacy_raw": "not parseable"}


def test_migrate_legacy_data_command_renders_report(monkeypatch, capsys):
    def fake_run_import(options):
        assert options.execute is False
        assert options.phases == ("manuscripts",)
        return ImportReport(
            dry_run=True,
            legacy_database="old_arch",
            target_database="new_target",
            phases=[
                PhaseResult(
                    key="manuscripts",
                    status="ok",
                    started_at="2026-05-29T00:00:00+00:00",
                    finished_at="2026-05-29T00:00:01+00:00",
                    rows_planned={"manuscripts_itemimage": 2},
                    rows_imported={},
                )
            ],
            target_row_counts_before={},
            target_row_counts_after={},
        )

    monkeypatch.setattr("apps.common.management.commands.migrate_legacy_data.run_import", fake_run_import)

    call_command("migrate_legacy_data", phase=["manuscripts"])
    output = capsys.readouterr().out
    data = json.loads(output.split("\nDry run only.")[0])

    assert data["dry_run"] is True
    assert data["phases"][0]["rows_planned"] == {"manuscripts_itemimage": 2}

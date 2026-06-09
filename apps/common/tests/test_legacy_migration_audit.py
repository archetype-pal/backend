from apps.common.legacy_migration_audit import (
    AuditReport,
    CheckResult,
    IdComparison,
    MappingResult,
    compare_id_sets,
    legacy_url_from_env,
    render_json,
    render_markdown,
    target_url_from_env,
)


def test_compare_id_sets_exact_match():
    comparison = compare_id_sets({1, 2, 3}, {1, 2, 3})

    assert comparison.common_count == 3
    assert comparison.missing_in_target_count == 0
    assert comparison.extra_in_target_count == 0
    assert comparison.unexpected_missing_count == 0
    assert comparison.unexpected_extra_count == 0


def test_compare_id_sets_allows_known_target_extras_and_missing_ids():
    comparison = compare_id_sets(
        {1, 2, 3, 4},
        {1, 2, 4, -1},
        allowed_extra_target_ids={-1},
        allowed_missing_target_ids={3},
    )

    assert comparison.missing_in_target_count == 1
    assert comparison.extra_in_target_count == 1
    assert comparison.unexpected_missing_count == 0
    assert comparison.unexpected_extra_count == 0
    assert comparison.missing_sample == [3]
    assert comparison.extra_sample == [-1]


def test_compare_id_sets_reports_unexpected_differences():
    comparison = compare_id_sets({1, 2, 3}, {1, 4})

    assert comparison.common_count == 1
    assert comparison.missing_in_target_count == 2
    assert comparison.extra_in_target_count == 1
    assert comparison.unexpected_missing_count == 2
    assert comparison.unexpected_extra_count == 1


def test_render_markdown_includes_mapping_and_check_details():
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[
            MappingResult(
                key="example",
                title="Example entity",
                category="example",
                strategy="id-preserved",
                status="warn",
                legacy_count=2,
                target_count=3,
                notes="target has a known placeholder",
                id_comparison=IdComparison(
                    legacy_count=2,
                    target_count=3,
                    common_count=2,
                    missing_in_target_count=0,
                    extra_in_target_count=1,
                    unexpected_missing_count=0,
                    unexpected_extra_count=0,
                    missing_sample=[],
                    extra_sample=[-1],
                ),
            )
        ],
        checks=[
            CheckResult(
                key="authors",
                title="Author mapping",
                status="warn",
                summary="Needs username mapping.",
                details=[{"legacy_username": "legacy", "target_username": "target"}],
            )
        ],
    )

    rendered = render_markdown(report)

    assert "Status: `warn`" in rendered
    assert "| `warn` | Example entity | 2 | 3 | id-preserved |" in rendered
    assert "target has a known placeholder" in rendered
    assert '"legacy_username": "legacy"' in rendered


def test_render_json_is_machine_readable():
    report = AuditReport(
        legacy_database="legacy_source",
        target_database="target_current",
        legacy_table_count=142,
        target_table_count=52,
        mappings=[],
        checks=[],
    )

    rendered = render_json(report)

    assert '"legacy_database": "legacy_source"' in rendered
    assert '"status": "ok"' in rendered


def test_database_urls_default_from_environment(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:secret@postgres:5432/target_current",
    )

    assert target_url_from_env() == "postgresql://postgres:secret@postgres:5432/target_current"
    assert legacy_url_from_env() == "postgresql://postgres:secret@postgres:5432/legacy_source"


def test_explicit_database_urls_override_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:secret@postgres:5432/target_current")
    monkeypatch.setenv("TARGET_DATABASE_URL", "postgresql://postgres:other@postgres:5432/current")
    monkeypatch.setenv("LEGACY_DATABASE_URL", "postgresql://postgres:other@postgres:5432/legacy")

    assert target_url_from_env() == "postgresql://postgres:other@postgres:5432/current"
    assert legacy_url_from_env() == "postgresql://postgres:other@postgres:5432/legacy"


def test_legacy_url_can_derive_from_explicit_target_url(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)

    assert (
        legacy_url_from_env(base_url="postgresql://postgres:secret@postgres:5432/current")
        == "postgresql://postgres:secret@postgres:5432/legacy_source"
    )


def test_legacy_url_can_derive_from_custom_legacy_database_name(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.setenv("LEGACY_DATABASE_NAME", "restored_legacy")

    assert (
        legacy_url_from_env(base_url="postgresql://postgres:secret@postgres:5432/current")
        == "postgresql://postgres:secret@postgres:5432/restored_legacy"
    )


def test_database_urls_fallback_to_postgres_environment(monkeypatch):
    monkeypatch.delenv("LEGACY_DATABASE_URL", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACY_DATABASE_NAME", raising=False)
    monkeypatch.delenv("TARGET_DATABASE_NAME", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret value")
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "compose_target")

    assert target_url_from_env() == "postgresql://postgres:secret%20value@postgres:5432/compose_target"
    assert legacy_url_from_env() == "postgresql://postgres:secret%20value@postgres:5432/legacy_source"

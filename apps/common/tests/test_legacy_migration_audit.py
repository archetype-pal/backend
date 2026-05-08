from apps.common.legacy_migration_audit import (
    AuditReport,
    CheckResult,
    IdComparison,
    MappingResult,
    compare_id_sets,
    render_json,
    render_markdown,
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
        legacy_database="old_arch",
        target_database="test_db",
        legacy_table_count=142,
        target_table_count=48,
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
        legacy_database="old_arch",
        target_database="test_db",
        legacy_table_count=142,
        target_table_count=48,
        mappings=[],
        checks=[],
    )

    rendered = render_json(report)

    assert '"legacy_database": "old_arch"' in rendered
    assert '"status": "ok"' in rendered

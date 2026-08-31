"""Tests for the Phase H.11 cutover gate (`verify_tei_cutover`).

The gate runs against a database that still has `content_dpt_legacy` while the
code no longer declares the field, so the tests recreate that column with raw
DDL (the `legacy_column` fixture) rather than through the ORM. Since migration
0025 dropped the column, a freshly migrated database never has it.
"""

from datetime import datetime, timedelta
from io import StringIO
from typing import cast

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone
import pytest

from apps.manuscripts.management.commands.verify_tei_cutover import (
    EXIT_FAILED,
    EXIT_NOTHING_TO_GATE,
    FAILURES_TABLE,
    LEGACY_COLUMN,
)
from apps.manuscripts.models import ImageText, StatusTransition
from apps.manuscripts.services.tei import data_dpt_to_tei
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

DPT = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation" data-graph-id="2824">salutem</span></p>'
)
TEI = data_dpt_to_tei(DPT)
TABLE = ImageText._meta.db_table

MIGRATED_AT = "2026-05-31"
_MIGRATION_INSTANT = timezone.make_aware(datetime(2026, 5, 31))
BEFORE_MIGRATION = _MIGRATION_INSTANT - timedelta(days=3)
AFTER_MIGRATION = _MIGRATION_INSTANT + timedelta(days=10)


def _has_legacy_column() -> bool:
    with connection.cursor() as cursor:
        return LEGACY_COLUMN in {col.name for col in connection.introspection.get_table_description(cursor, TABLE)}


@pytest.fixture
def legacy_column():
    """Ensure `content_dpt_legacy` exists for the test row(s).

    Migration 0025 drops the column, so on a freshly migrated database this
    adds it back; on a database that predates the drop it is a no-op. There is
    no teardown: the DDL runs inside the test's transaction and is rolled back
    with it. Dropping it explicitly instead fails on PostgreSQL — by teardown
    the transaction holds pending trigger events from the inserted rows, and
    ALTER TABLE is refused.
    """
    if not _has_legacy_column():
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {LEGACY_COLUMN} text NULL")
    yield


def _make(content: str) -> ImageText:
    return cast(
        ImageText,
        ImageText.objects.create(
            item_image=ItemImageFactory(),
            content=content,
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            language="la",
        ),
    )


def _set_legacy(image_text: ImageText, value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"UPDATE {TABLE} SET {LEGACY_COLUMN} = %s WHERE id = %s", [value, image_text.id])


def _set_modified(image_text: ImageText, when: datetime) -> None:
    """`modified` is auto_now, so it can only be set by going round the ORM save."""
    ImageText.objects.filter(pk=image_text.pk).update(modified=when)


def _add_status_transition(image_text: ImageText, when: datetime) -> None:
    """Record a status change at `when` — `created` is auto_now_add, hence the update."""
    transition = StatusTransition.objects.create(
        image_text=image_text,
        actor=None,
        from_status=ImageText.Status.DRAFT,
        to_status=ImageText.Status.LIVE,
    )
    StatusTransition.objects.filter(pk=transition.pk).update(created=when)


def _diverging_row(*, modified: datetime, legacy: str = "<p>pre-edit html</p>") -> ImageText:
    """A row whose retained HTML the current TEI cannot reproduce."""
    text = _make(TEI)
    _set_legacy(text, legacy)
    _set_modified(text, modified)
    return text


def _run(*args: str) -> str:
    out = StringIO()
    call_command("verify_tei_cutover", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def _run_failing(*args: str, code: int = EXIT_FAILED) -> str:
    out = StringIO()
    with pytest.raises(SystemExit) as exc_info:
        call_command("verify_tei_cutover", *args, stdout=out, stderr=StringIO())
    assert exc_info.value.code == code
    return out.getvalue()


def test_clean_corpus_passes_and_changes_nothing(legacy_column):
    text = _make(TEI)
    _set_legacy(text, DPT)

    report = _run()

    assert "[PASS] corpus-size" in report
    assert "[PASS] tei-wellformed" in report
    assert "[PASS] no-data-dpt-residue" in report
    assert "[PASS] legacy-not-sole-copy" in report
    assert "[PASS] legacy-regenerable" in report
    assert "[PASS] legacy-superseded" in report
    assert f"[SKIP] {FAILURES_TABLE}" in report
    assert "All mechanical checks passed" in report

    # Read-only: neither column moved.
    text.refresh_from_db()
    assert text.content == TEI
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {LEGACY_COLUMN} FROM {TABLE} WHERE id = %s", [text.id])
        assert cursor.fetchone()[0] == DPT


def test_malformed_tei_fails(legacy_column):
    text = _make("<seg>unclosed")
    _set_legacy(text, DPT)

    report = _run_failing()

    assert "[FAIL] tei-wellformed" in report
    assert f"ImageText #{text.id}" in report


def test_non_regenerable_legacy_fails(legacy_column):
    text = _make(TEI)
    _set_legacy(text, "<p>something the TEI cannot reproduce</p>")

    report = _run_failing()

    assert "[FAIL] legacy-regenerable" in report
    assert f"ImageText #{text.id}" in report


def test_legacy_only_row_fails(legacy_column):
    text = _make("")
    _set_legacy(text, DPT)

    report = _run_failing()

    assert "[FAIL] legacy-not-sole-copy" in report
    assert f"ImageText #{text.id}" in report


def test_data_dpt_residue_fails(legacy_column):
    # Content still in legacy HTML: the migration never completed here, or a
    # rollback was executed. Either way the cutover must not proceed.
    text = _make(DPT)

    report = _run_failing()

    assert "[FAIL] no-data-dpt-residue" in report
    assert f"ImageText #{text.id}" in report


# --- the --migrated-at waiver -------------------------------------------------


def test_migrated_at_waives_only_rows_modified_after_it(legacy_column):
    """The boundary the whole waiver rests on: earlier rows are still failures."""
    stale = _diverging_row(modified=BEFORE_MIGRATION)
    edited = _diverging_row(modified=AFTER_MIGRATION)
    # Verified alongside, so the regenerable check has something real to affirm.
    _set_legacy(_make(TEI), DPT)

    report = _run_failing("--migrated-at", MIGRATED_AT, "--accept-superseded")

    regenerable, superseded = _section(report, "legacy-regenerable"), _section(report, "legacy-superseded")
    assert regenerable.startswith("[FAIL]")
    assert f"ImageText #{stale.id}" in regenerable
    assert f"ImageText #{edited.id}" not in regenerable
    assert superseded.startswith("[REVIEW]")
    assert f"ImageText #{edited.id}" in superseded
    assert f"ImageText #{stale.id}" not in superseded


def test_superseded_rows_block_without_acknowledgement(legacy_column):
    edited = _diverging_row(modified=AFTER_MIGRATION)
    _set_legacy(_make(TEI), DPT)

    report = _run_failing("--migrated-at", MIGRATED_AT)

    assert "[FAIL] legacy-superseded" in report
    assert f"ImageText #{edited.id}" in report
    assert "WILL be destroyed by the drop" in report


def test_accepted_superseded_rows_pass_but_the_verdict_says_bytes_are_lost(legacy_column):
    edited = _diverging_row(modified=AFTER_MIGRATION)
    _set_legacy(_make(TEI), DPT)

    report = _run("--migrated-at", MIGRATED_AT, "--accept-superseded")

    assert "[REVIEW] legacy-superseded" in report
    assert f"ImageText #{edited.id}" in report
    assert "1 accepted superseded row(s)" in report
    # The blanket claim must not be made while bytes are being destroyed.
    assert "All mechanical checks passed" not in report


def test_waiving_every_retained_value_fails_even_when_accepted(legacy_column):
    """A --migrated-at earlier than the migration excuses the whole corpus."""
    _diverging_row(modified=AFTER_MIGRATION)
    _diverging_row(modified=AFTER_MIGRATION)

    report = _run_failing("--migrated-at", MIGRATED_AT, "--accept-superseded")

    assert "[FAIL] legacy-regenerable" in report
    assert "0 of 2 retained value(s) were actually verified" in report


def test_status_change_alone_does_not_waive_a_lossy_row(legacy_column):
    """Draft→Review→Live bumps `modified` without touching `content`."""
    text = _diverging_row(modified=AFTER_MIGRATION)
    _add_status_transition(text, AFTER_MIGRATION)
    _set_legacy(_make(TEI), DPT)

    report = _run_failing("--migrated-at", MIGRATED_AT, "--accept-superseded")

    assert "[FAIL] legacy-regenerable" in report
    assert f"ImageText #{text.id}" in _section(report, "legacy-regenerable")


def test_content_edit_after_a_status_change_is_still_superseded(legacy_column):
    """An old transition must not stop a later genuine edit from counting."""
    text = _diverging_row(modified=AFTER_MIGRATION)
    _add_status_transition(text, AFTER_MIGRATION - timedelta(days=2))
    _set_legacy(_make(TEI), DPT)

    report = _run("--migrated-at", MIGRATED_AT, "--accept-superseded")

    assert f"ImageText #{text.id}" in _section(report, "legacy-superseded")


# --- corpus size --------------------------------------------------------------


def test_empty_corpus_fails(legacy_column):
    report = _run_failing()

    assert "image-text rows: 0" in report
    assert "[FAIL] corpus-size" in report
    assert "check DATABASE_URL" in report
    assert "All mechanical checks passed" not in report


def test_corpus_smaller_than_expected_fails(legacy_column):
    _set_legacy(_make(TEI), DPT)

    report = _run_failing("--min-rows", "899")

    assert "[FAIL] corpus-size" in report
    assert "1 image-text row(s), expected at least 899" in report


def test_min_rows_below_one_is_a_command_error(legacy_column):
    with pytest.raises(CommandError):
        call_command("verify_tei_cutover", "--min-rows", "0", stdout=StringIO(), stderr=StringIO())


# --- reporting ----------------------------------------------------------------


def test_report_limit_truncates_offenders(legacy_column):
    for _ in range(3):
        _set_legacy(_make(TEI), "<p>divergent</p>")

    report = _run_failing("--report-limit", "1")

    assert "... and 2 more" in report


def test_report_limit_below_one_is_a_command_error(legacy_column):
    with pytest.raises(CommandError):
        call_command("verify_tei_cutover", "--report-limit", "0", stdout=StringIO(), stderr=StringIO())


def test_passing_checks_never_print_a_truncation_trailer(legacy_column):
    _set_legacy(_make(TEI), DPT)

    report = _run("--report-limit", "1")

    assert "more" not in report.split("[PASS] corpus-size")[1].split("[SKIP]")[0]


# --- tei_migration_failures ---------------------------------------------------


def test_populated_failures_table_blocks_cutover(legacy_column):
    _set_legacy(_make(TEI), DPT)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE {FAILURES_TABLE} (image_text_id integer)")
        cursor.execute(f"INSERT INTO {FAILURES_TABLE} (image_text_id) VALUES (1)")
    try:
        report = _run_failing()
        assert f"[FAIL] {FAILURES_TABLE}" in report
        assert "1 unreviewed migration failure(s) recorded" in report
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {FAILURES_TABLE}")


def test_empty_failures_table_passes(legacy_column):
    _set_legacy(_make(TEI), DPT)
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE TABLE {FAILURES_TABLE} (image_text_id integer)")
    try:
        assert "table present and empty" in _run()
    finally:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {FAILURES_TABLE}")


def test_absent_failures_table_is_a_skip_not_evidence(legacy_column):
    _set_legacy(_make(TEI), DPT)

    report = _run()

    assert f"[SKIP] {FAILURES_TABLE}" in report
    assert "carries no evidence" in report


# --- already-cut-over database ------------------------------------------------


@pytest.fixture
def without_legacy_column():
    """Simulate a database where the column really has been dropped.

    Migration 0024 is state-only, so a migrated database still HAS the column;
    this drops it for the duration of the test to exercise the
    nothing-to-gate path.
    """
    existed = _has_legacy_column()
    if existed:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {TABLE} DROP COLUMN {LEGACY_COLUMN}")
    yield
    if existed:
        with connection.cursor() as cursor:
            cursor.execute(f"ALTER TABLE {TABLE} ADD COLUMN {LEGACY_COLUMN} text NULL")


@pytest.mark.django_db(transaction=True)
def test_absent_legacy_column_exits_nothing_to_gate(without_legacy_column):
    _make(TEI)

    report = _run_failing(code=EXIT_NOTHING_TO_GATE)

    assert "[SKIP] legacy-column" in report
    assert "already gone" in report
    assert "rows with retained legacy html: n/a" in report
    assert "That is not a verification" in report
    assert "All mechanical checks passed" not in report


def test_invalid_migrated_at_is_a_command_error(legacy_column):
    with pytest.raises(CommandError):
        call_command("verify_tei_cutover", "--migrated-at", "not-a-date", stdout=StringIO(), stderr=StringIO())


def _section(report: str, check_name: str) -> str:
    """The `[STATUS] <check_name> …` line plus the detail lines beneath it."""
    lines = report.splitlines()
    start = next(index for index, line in enumerate(lines) if f"] {check_name} " in line)
    end = start + 1
    while end < len(lines) and lines[end].startswith("    "):
        end += 1
    return "\n".join(lines[start:end])

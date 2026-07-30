"""Tests for the Phase H.3 data-dpt → TEI migration command.

Forward-only since H.11 dropped `content_dpt_legacy`; the rollback path (and
its tests) went with the column.
"""

from io import StringIO
from typing import cast

from django.core.management import call_command
import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

DPT = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation" data-graph-id="2824">salutem</span></p>'
)
# Reordered data-dpt attributes don't round-trip: the reverse converter emits
# them in canonical order, so the result differs from the original and the row
# is skipped (entity/quote differences are normalised by the canonical verify,
# but attribute order is not).
NON_ROUNDTRIP = '<span data-dpt-type="address" data-dpt-cat="words" data-dpt="clause">x</span>'


def _make(content: str, **kwargs) -> ImageText:
    return cast(
        ImageText,
        ImageText.objects.create(
            item_image=ItemImageFactory(),
            content=content,
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            language="la",
            **kwargs,
        ),
    )


def test_dry_run_does_not_write():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei")  # dry-run default
    text.refresh_from_db()
    assert text.content == DPT


def test_apply_flips_content():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    assert '<seg type="salutation" corresp="#gid-2824">salutem</seg>' in text.content
    assert "data-dpt" not in text.content


def test_apply_is_idempotent():
    # Without the legacy column, re-running has to recognise its own TEI output
    # instead of re-converting the retained data-dpt.
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    first = text.content
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    assert text.content == first


def test_already_tei_rows_are_skipped_not_failed():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()

    out = StringIO()
    call_command("migrate_imagetext_to_tei", "--apply", stdout=out)
    report = out.getvalue()
    assert "already_tei: 1" in report
    assert "failed: 0" in report
    # The skip is auditable, not just a count: a re-run's no-op claim has to be
    # checkable against the set of rows the operator expects to be TEI already.
    assert f"already-TEI ids (first 25): {text.id}" in report


def test_plain_html_is_a_failure_not_a_silent_already_tei_skip():
    # No data-dpt and well-formed, but not TEI either: the reverse converter
    # merely re-renders it (single quotes -> double), which must NOT be read as
    # "already migrated". Such a row belongs in `failed`, for manual review.
    text = _make("<p style='color:red'>hello</p>")

    out = StringIO()
    call_command("migrate_imagetext_to_tei", "--apply", stdout=out)
    report = out.getvalue()

    assert "already_tei: 0" in report
    assert "failed: 1" in report
    assert f"failed ids (first 25): {text.id}" in report
    text.refresh_from_db()
    assert text.content == "<p style='color:red'>hello</p>"


def test_non_roundtrip_row_is_skipped():
    text = _make(NON_ROUNDTRIP)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    # Left as data-dpt for manual review.
    assert text.content == NON_ROUNDTRIP


def test_limit_processes_at_most_n_rows():
    _make(DPT)
    _make(DPT)
    out = StringIO()
    call_command("migrate_imagetext_to_tei", "--apply", "--limit", "1", stdout=out)
    assert "written: 1" in out.getvalue()
    assert ImageText.objects.filter(content=DPT).count() == 1


def test_apply_skips_non_wellformed_tei():
    # Content that round-trips but is NOT well-formed XML (raw &) must be left
    # as data-dpt, not written as bogus "TEI" that later fails verify_tei.
    text = _make("<p>Tom & Jerry</p>")
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    assert text.content == "<p>Tom & Jerry</p>"

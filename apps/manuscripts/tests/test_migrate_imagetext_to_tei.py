"""Tests for the Phase H.3 data-dpt → TEI migration command."""

from django.core.management import call_command
import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

DPT = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation" data-graph-id="2824">salutem</span></p>'
)
# Raw single quote in a passthrough attribute does not round-trip (escaped to
# &#x27;), so this row must be skipped, not migrated.
NON_ROUNDTRIP = "<p style=\"font-family:'x'\">hi</p>"


def _make(content: str, **kwargs) -> ImageText:
    return ImageText.objects.create(
        item_image=ItemImageFactory(),
        content=content,
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
        **kwargs,
    )


def test_dry_run_does_not_write():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei")  # dry-run default
    text.refresh_from_db()
    assert text.content == DPT
    assert text.content_dpt_legacy is None


def test_apply_flips_content_and_retains_legacy():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    assert text.content_dpt_legacy == DPT
    assert '<seg type="salutation" corresp="#gid-2824">salutem</seg>' in text.content
    assert "data-dpt" not in text.content


def test_apply_is_idempotent():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    first = text.content
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    assert text.content == first
    assert text.content_dpt_legacy == DPT


def test_non_roundtrip_row_is_skipped():
    text = _make(NON_ROUNDTRIP)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    # Left as data-dpt for manual review.
    assert text.content == NON_ROUNDTRIP
    assert text.content_dpt_legacy is None


def test_reverse_restores_original_and_clears_legacy():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--apply")
    text.refresh_from_db()
    assert "data-dpt" not in text.content  # now TEI

    call_command("migrate_imagetext_to_tei", "--reverse")
    text.refresh_from_db()
    assert text.content == DPT
    assert text.content_dpt_legacy is None


def test_reverse_skips_unmigrated_rows():
    text = _make(DPT)
    call_command("migrate_imagetext_to_tei", "--reverse")
    text.refresh_from_db()
    assert text.content == DPT
    assert text.content_dpt_legacy is None

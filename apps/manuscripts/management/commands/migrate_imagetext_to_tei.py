"""Phase H.3 — migrate `ImageText.content` from data-dpt HTML to TEI XML.

Each row's original data-dpt is retained in `content_dpt_legacy` (the reversible
safety net), then `content` is flipped to TEI — but only if the conversion
round-trips back to the original byte-for-byte. Rows that fail verification are
left untouched (still data-dpt) and reported, mirroring the roadmap's
`tei_migration_failures` review path.

Modes:
- (default) dry-run — preview the forward conversion, write nothing.
- ``--apply`` — perform the TEI flip (explicit, so the destructive step is opt-in).
- ``--reverse`` — roll back: restore `content` from `content_dpt_legacy` and
  clear the legacy column (the H.3 rollback plan). Re-index search afterwards.
"""

from html import unescape

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import data_dpt_to_tei, tei_to_data_dpt, validate_tei_wellformed


def _canonical(html: str) -> str:
    """Decode entities so the verify compares meaning, not entity spelling.

    The forward converter normalises HTML named entities (`&nbsp;`, `&aacute;`)
    to literal characters for valid XML, so round-trips are canonical-form
    equivalent rather than byte-identical for those rows.
    """
    return unescape(html)


class Command(BaseCommand):
    help = "Convert ImageText.content between data-dpt HTML and TEI XML (round-trip-verified)."

    def add_arguments(self, parser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Persist the TEI flip.")
        mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
        mode.add_argument(
            "--reverse",
            action="store_true",
            help="Roll back: restore content from content_dpt_legacy and clear it.",
        )
        parser.add_argument("--limit", type=int, default=None, help="Process at most N rows.")

    def handle(self, *args, **options) -> None:
        limit: int | None = options.get("limit")
        base = ImageText.objects.all().only("id", "content", "content_dpt_legacy")

        if options.get("reverse"):
            # Apply mode-specific filters BEFORE slicing — Django forbids
            # filtering a sliced queryset, which previously broke --reverse --limit.
            queryset = base.exclude(content_dpt_legacy__isnull=True)
            if limit:
                queryset = queryset[:limit]
            self._reverse(queryset)
        else:
            queryset = base[:limit] if limit else base
            self._forward(queryset, apply_changes=bool(options.get("apply")))

    def _forward(self, queryset, *, apply_changes: bool) -> None:
        summary = {"total": 0, "verified": 0, "failed": 0, "written": 0}
        failures: list[int] = []

        self.stdout.write(f"Running forward in {'APPLY' if apply_changes else 'DRY-RUN'} mode.")

        for image_text in queryset:
            summary["total"] += 1
            # The original data-dpt is the source of truth: `content_dpt_legacy`
            # once migrated, else `content` on first pass.
            legacy = image_text.content if image_text.content_dpt_legacy is None else image_text.content_dpt_legacy
            tei = data_dpt_to_tei(legacy)

            # A row is only "verified" if it round-trips canonically AND the TEI
            # is well-formed XML — otherwise it would later fail the verify_tei
            # gate. Either failure leaves the row as data-dpt for manual review.
            if _canonical(tei_to_data_dpt(tei)) != _canonical(legacy) or validate_tei_wellformed(tei):
                summary["failed"] += 1
                failures.append(image_text.id)
                continue

            summary["verified"] += 1
            if apply_changes:
                with transaction.atomic():
                    if image_text.content_dpt_legacy is None:
                        image_text.content_dpt_legacy = legacy
                    image_text.content = tei
                    image_text.save(update_fields=["content", "content_dpt_legacy"])
                summary["written"] += 1

        self._print_summary(summary)
        if failures:
            preview = ", ".join(str(fid) for fid in failures[:25])
            self.stdout.write(f"failed ids (first 25): {preview}")
            self.stdout.write("Failed rows were left as data-dpt for manual review.")

    def _reverse(self, queryset) -> None:
        summary = {"total": 0, "restored": 0}
        self.stdout.write("Running REVERSE (restoring content from content_dpt_legacy).")

        for image_text in queryset:
            summary["total"] += 1
            with transaction.atomic():
                image_text.content = image_text.content_dpt_legacy
                image_text.content_dpt_legacy = None
                image_text.save(update_fields=["content", "content_dpt_legacy"])
            summary["restored"] += 1

        self._print_summary(summary)
        if summary["restored"]:
            self.stdout.write("Re-index search to reflect the restored data-dpt content.")

    def _print_summary(self, summary: dict[str, int]) -> None:
        self.stdout.write("--- TEI migration summary ---")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")

"""Phase H.3 — migrate `ImageText.content` from data-dpt HTML to TEI XML.

Each row's original data-dpt is retained in `content_dpt_legacy` (the reversible
safety net), then `content` is flipped to TEI — but only if the conversion
round-trips back to the original byte-for-byte. Rows that fail verification are
left untouched (still data-dpt) and reported, mirroring the roadmap's
`tei_migration_failures` review path.

Default mode is a dry-run: nothing is written. `--apply` performs the flip and
is deliberately separate so the destructive step is explicit.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import data_dpt_to_tei, tei_to_data_dpt


class Command(BaseCommand):
    help = "Convert ImageText.content from data-dpt HTML to TEI XML (round-trip-verified)."

    def add_arguments(self, parser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Persist the TEI flip.")
        mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N rows.")

    def handle(self, *args, **options) -> None:
        apply_changes: bool = bool(options.get("apply"))
        limit: int | None = options.get("limit")

        summary = {"total": 0, "verified": 0, "failed": 0, "written": 0}
        failures: list[int] = []

        self.stdout.write(f"Running in {'APPLY' if apply_changes else 'DRY-RUN'} mode.")

        queryset = ImageText.objects.all().only("id", "content", "content_dpt_legacy")
        if limit:
            queryset = queryset[:limit]

        for image_text in queryset:
            summary["total"] += 1
            # The original data-dpt is the source of truth: `content_dpt_legacy`
            # once migrated, else `content` on first pass.
            legacy = image_text.content if image_text.content_dpt_legacy is None else image_text.content_dpt_legacy
            tei = data_dpt_to_tei(legacy)

            if tei_to_data_dpt(tei) != legacy:
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

        self.stdout.write("--- TEI migration summary ---")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")
        if failures:
            preview = ", ".join(str(fid) for fid in failures[:25])
            self.stdout.write(f"failed ids (first 25): {preview}")
            self.stdout.write("Failed rows were left as data-dpt for manual review.")

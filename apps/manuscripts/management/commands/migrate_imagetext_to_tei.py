"""Phase H.3 — migrate `ImageText.content` from data-dpt HTML to TEI XML.

Forward-only since the H.11 cutover dropped `content_dpt_legacy`: there is no
retention column left to write, and therefore no `--reverse`. The command still
earns its place because it is step 3 of the offline backup-migration pipeline
(`scripts/migrate_backup_to_tei.sh`, `docs/tei-backup-migration.md`) — data-dpt
dumps still arrive and still have to be converted before they can be restored.

`content` is only flipped when the conversion round-trips back to the original
(canonical-form) *and* the result is well-formed XML. Rows that fail either
check are left untouched (still data-dpt) and reported, mirroring the roadmap's
`tei_migration_failures` review path. Rows that are already TEI are skipped, so
re-running is a no-op — before H.11 that idempotence came for free from the
legacy column; now it has to be recognised from `content` itself.

Modes:
- (default) dry-run — preview the forward conversion, write nothing.
- ``--apply`` — perform the TEI flip (explicit, so the destructive step is opt-in).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import (
    canonical_data_dpt,
    contains_tei_element,
    data_dpt_to_tei,
    tei_to_data_dpt,
    validate_tei_wellformed,
)

# How many row ids each reported bucket prints before truncating.
_ID_PREVIEW = 25


def _is_already_tei(content: str) -> bool:
    """True when `content` is this command's own output, so it must be skipped.

    Three conditions, all required: no `data-dpt` markup left, well-formed XML,
    and at least one element the mapping actually treats as TEI (`seg`,
    `persName`, …). Without this guard a re-run would feed TEI to the forward
    converter and report every already-migrated row as a round-trip failure.

    The TEI-element test is positive identification, deliberately: inferring it
    from `tei_to_data_dpt(content) != content` also matches plain unmigrated
    HTML that the reverse converter merely re-renders — e.g. single-quoted
    attributes, which this corpus contains (see `escape_attr`) — and would
    silently reclassify a row bound for manual review as already-migrated.
    """
    if "data-dpt" in content:
        return False
    if validate_tei_wellformed(content):
        return False
    return contains_tei_element(content)


class Command(BaseCommand):
    help = "Convert ImageText.content from data-dpt HTML to TEI XML (round-trip-verified, forward-only)."

    def add_arguments(self, parser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--apply", action="store_true", help="Persist the TEI flip.")
        mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N rows.")

    def handle(self, *args, **options) -> None:
        limit: int | None = options.get("limit")
        queryset = ImageText.objects.all().only("id", "content")
        if limit:
            queryset = queryset[:limit]
        self._forward(queryset, apply_changes=bool(options.get("apply")))

    def _forward(self, queryset, *, apply_changes: bool) -> None:
        summary = {"total": 0, "already_tei": 0, "verified": 0, "failed": 0, "written": 0}
        failures: list[int] = []
        skipped: list[int] = []

        self.stdout.write(f"Running forward in {'APPLY' if apply_changes else 'DRY-RUN'} mode.")

        for image_text in queryset:
            summary["total"] += 1
            legacy = image_text.content or ""

            if _is_already_tei(legacy):
                summary["already_tei"] += 1
                skipped.append(image_text.id)
                continue

            tei = data_dpt_to_tei(legacy)

            # A row is only "verified" if it round-trips canonically AND the TEI
            # is well-formed XML — otherwise it would later fail the verify_tei
            # gate. Either failure leaves the row as data-dpt for manual review.
            if canonical_data_dpt(tei_to_data_dpt(tei)) != canonical_data_dpt(legacy) or validate_tei_wellformed(tei):
                summary["failed"] += 1
                failures.append(image_text.id)
                continue

            summary["verified"] += 1
            if apply_changes:
                with transaction.atomic():
                    image_text.content = tei
                    image_text.save(update_fields=["content"])
                summary["written"] += 1

        self._print_summary(summary)
        if failures:
            self.stdout.write(f"failed ids (first {_ID_PREVIEW}): {self._preview(failures)}")
            self.stdout.write("Failed rows were left as data-dpt for manual review.")
        if skipped:
            # Printed, not just counted: the skip is the only thing standing
            # between a re-run and re-converting already-TEI rows, so its
            # no-op claim has to be checkable against the expected set.
            self.stdout.write(f"already-TEI ids (first {_ID_PREVIEW}): {self._preview(skipped)}")

    def _preview(self, ids: list[int]) -> str:
        shown = ", ".join(str(row_id) for row_id in ids[:_ID_PREVIEW])
        return shown if len(ids) <= _ID_PREVIEW else f"{shown}, ... (+{len(ids) - _ID_PREVIEW} more)"

    def _print_summary(self, summary: dict[str, int]) -> None:
        self.stdout.write("--- TEI migration summary ---")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")

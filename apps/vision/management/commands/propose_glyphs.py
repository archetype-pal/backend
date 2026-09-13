"""W1.1 — propose glyph regions for unannotated pages.

A command rather than an endpoint, for the same reason as the text pipelines:
these runs are corpus-wide and expensive, and a request path that starts one is
a request path that can start a thousand.
"""

from typing import Any

from django.core.management.base import BaseCommand

from apps.vision.services import detection


class Command(BaseCommand):
    help = "Ask a hosted vision model for glyph boxes and file them in the annotation review queue."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many pages.")
        parser.add_argument("--provider", default=detection.PROVIDER)
        parser.add_argument("--model", default=None, help="Override the provider's default model.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent and call no model. Still resolves page dimensions.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        depth_before = detection.queue_depth()
        tally = detection.run(
            limit=options["limit"],
            provider=options["provider"],
            model=options["model"],
            dry_run=options["dry_run"],
        )
        for name, count in tally.items():
            self.stdout.write(f"{name}: {count}")

        if tally["unavailable"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{tally['unavailable']} pages could not be fetched or measured, so no box was proposed "
                    f"for them — a box placed without the page height would be mirrored."
                )
            )
        if tally["refused"]:
            self.stdout.write(self.style.WARNING("Refused: a spend cap or the hosted-provider gate stopped the run."))
        if tally["proposed"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Review queue: {depth_before} → {detection.queue_depth()}. Nothing has entered the record."
                )
            )

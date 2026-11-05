"""W1.1 — propose letters on pages with the letter models trained on this corpus.

A command, as `propose_glyphs` is: a run works through the corpus page by page.
Everything runs on our own server, so a run costs nothing, but it fills the
review queue; `--limit` and `--image` keep it to what reviewers can take.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.manuscripts.models import ItemImage
from apps.vision.services import detection, letters


class Command(BaseCommand):
    help = "Find letters on pages with the self-hosted letter models and file the likeliest in the review queue."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many pages.")
        parser.add_argument(
            "--image", type=int, action="append", default=None, help="Propose on this page (repeatable)."
        )
        parser.add_argument(
            "--per-allograph",
            type=int,
            default=letters.PER_ALLOGRAPH,
            help="At most this many proposals of each allograph on a page.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        selection = None
        if options["image"]:
            selection = list(ItemImage.objects.filter(pk__in=options["image"]).order_by("pk"))
            missing = set(options["image"]) - {image.pk for image in selection}
            if missing:
                raise CommandError(f"No such image: {', '.join(map(str, sorted(missing)))}.")
        depth_before = detection.queue_depth()
        tally = letters.run(limit=options["limit"], selection=selection, per_allograph=options["per_allograph"])
        for name, count in tally.items():
            self.stdout.write(f"{name}: {count}")
        if tally["unavailable"]:
            self.stdout.write(self.style.WARNING(f"{tally['unavailable']} pages could not be fetched or measured."))
        if tally["refused"]:
            self.stdout.write(self.style.WARNING("Refused: inference is switched off or a cap stopped the run."))
        if tally["failed"]:
            self.stdout.write(
                self.style.WARNING(f"{tally['failed']} pages failed; the model runs say why (is ML_HTR_URL set?).")
            )
        if tally["proposed"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Review queue: {depth_before} → {detection.queue_depth()}. Nothing has entered the record."
                )
            )

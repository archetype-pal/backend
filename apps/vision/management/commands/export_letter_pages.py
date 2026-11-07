"""Export the pages a glyph release annotates, for `htr/train_letters.py` (W1.1).

The release holds geometry only; the letter models learn from pictures. This
writes each annotated page as the HTR service is sent it, with `pages.json`.
These are the holding repositories' photographs: the directory is for training
on this server, never for publishing.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.ml.evaluation import ReleaseError, load_release
from apps.vision.services import letters


class Command(BaseCommand):
    help = "Write a glyph release's annotated pages as JPEGs for training the letter models."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--release", required=True, help="A directory export_glyph_dataset wrote.")
        parser.add_argument("--out", required=True, help="Where to write the pages and pages.json.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            release = load_release(options["release"])
        except ReleaseError as exc:
            raise CommandError(str(exc)) from exc
        tally = letters.export_pages(release.path, Path(options["out"]))
        for name, count in tally.items():
            self.stdout.write(f"{name}: {count}")
        if tally["unavailable"]:
            self.stdout.write(
                self.style.WARNING(f"{tally['unavailable']} pages could not be fetched; run again to retry them.")
            )

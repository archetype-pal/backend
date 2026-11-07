"""W1.4 — measure a model's CER, or draft the untranscribed tail.

`--evaluate` is the default, and deliberately: the target in §7.2 is a
measurement, and drafting 2,713 pages from a model whose error rate nobody has
checked is how a corpus acquires 2,713 plausible fictions.
"""

import json
from typing import Any

from django.core.management.base import BaseCommand

from apps.vision import images
from apps.vision.services import htr


class Command(BaseCommand):
    help = "Score a model's transcription CER against expert transcriptions, or draft new ones."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Draft transcriptions for images that have none. Without this, only measures.",
        )
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--provider", default=htr.PROVIDER)
        parser.add_argument("--model", default=None)
        parser.add_argument(
            "--size",
            type=int,
            default=images.RENDITION,
            help=f"The page's longer side in pixels, never enlarged (default {images.RENDITION}).",
        )
        parser.add_argument(
            "--effort",
            choices=["low", "medium", "high", "xhigh", "max"],
            default=None,
            help="How hard a model that takes an effort setting works on each page.",
        )
        parser.add_argument(
            "--max-tokens",
            type=int,
            default=htr.MAX_TOKENS,
            help="The most a model may write for one page, thinking included.",
        )
        parser.add_argument(
            "--style",
            choices=htr.STYLES,
            default=htr.DIPLOMATIC,
            help=(
                "What the model is asked for and scored against: what is on the parchment (diplomatic), "
                "or the corpus's edited text, abbreviations expanded (edited)."
            ),
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=1,
            help="How many pages to read at once. A hosted model can take minutes over one page.",
        )
        parser.add_argument("--out", default="", help="Write the per-image scores to this JSON file.")
        parser.add_argument("--dry-run", action="store_true", help="Count the selection and call no model.")

    def handle(self, *args: Any, **options: Any) -> None:
        reading = {
            "size": options["size"],
            "effort": options["effort"],
            "max_tokens": options["max_tokens"],
            "workers": max(1, options["workers"]),
            "style": options["style"],
        }
        if options["draft"]:
            tally = htr.transcribe(
                limit=options["limit"],
                provider=options["provider"],
                model=options["model"],
                dry_run=options["dry_run"],
                **reading,
            )
            for name, count in tally.items():
                self.stdout.write(f"{name}: {count}")
            if tally["queue_full"]:
                self.stdout.write(self.style.WARNING("Stopped: the drafts waiting for review have reached the limit."))
            if tally["drafted"]:
                self.stdout.write(
                    self.style.SUCCESS(f"{tally['drafted']} drafts created, all marked machine-drafted and none Live.")
                )
            return

        if options["dry_run"]:
            self.stdout.write(f"ground truth available: {len(htr.transcribed())} transcriptions")
            return

        summary = htr.evaluate(limit=options["limit"], provider=options["provider"], model=options["model"], **reading)
        per_image = summary.pop("per_image")
        for name, value in summary.items():
            self.stdout.write(f"{name}: {value}")

        if options["out"]:
            with open(options["out"], "w", encoding="utf-8") as handle:
                json.dump({"summary": summary, "per_image": per_image}, handle, indent=2)
            self.stdout.write(f"per-image scores → {options['out']}")

        if summary["median_cer"] is None:
            self.stdout.write(self.style.WARNING("Nothing was scored; there is no baseline to report."))
        elif summary["target_met"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Median CER {summary['median_cer']} clears the <10% target. Note what this does not "
                    f"say: it is one model against expert transcriptions. Set it beside the others "
                    f"(the hosted default, or the self-hosted `--provider kraken`) before choosing."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Median CER {summary['median_cer']} misses the <10% target. Drafting the "
                    f"untranscribed tail at this error rate is not worth a reviewer's time."
                )
            )

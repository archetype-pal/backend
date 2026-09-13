"""W1.4 — measure a hosted model's CER, or draft the untranscribed tail.

`--evaluate` is the default, and deliberately: the target in §7.2 is a
measurement, and drafting 2,713 pages from a model whose error rate nobody has
checked is how a corpus acquires 2,713 plausible fictions.
"""

import json
from typing import Any

from django.core.management.base import BaseCommand

from apps.vision.services import htr


class Command(BaseCommand):
    help = "Score a hosted model's transcription CER against expert transcriptions, or draft new ones."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--draft",
            action="store_true",
            help="Draft transcriptions for images that have none. Without this, only measures.",
        )
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--provider", default=htr.PROVIDER)
        parser.add_argument("--model", default=None)
        parser.add_argument("--out", default="", help="Write the per-image scores to this JSON file.")
        parser.add_argument("--dry-run", action="store_true", help="Count the selection and call no model.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["draft"]:
            tally = htr.transcribe(
                limit=options["limit"],
                provider=options["provider"],
                model=options["model"],
                dry_run=options["dry_run"],
            )
            for name, count in tally.items():
                self.stdout.write(f"{name}: {count}")
            if tally["drafted"]:
                self.stdout.write(
                    self.style.SUCCESS(f"{tally['drafted']} drafts created, all marked machine-drafted and none Live.")
                )
            return

        if options["dry_run"]:
            self.stdout.write(f"ground truth available: {len(htr.transcribed())} transcriptions")
            return

        summary = htr.evaluate(limit=options["limit"], provider=options["provider"], model=options["model"])
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
                    f"say: it is one hosted model against expert transcriptions, not a comparison with "
                    f"CATMuS-Medieval or Transkribus, which §7.2 still asks for."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Median CER {summary['median_cer']} misses the <10% target. Drafting the "
                    f"untranscribed tail at this error rate is not worth a reviewer's time."
                )
            )

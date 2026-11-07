"""What the review queue got through over a window, model by model, against annotating by hand.

See `apps.annotations.services.throughput` for what is counted and how time is
read. `annotation_throughput` is the pre-AI baseline in annotations per active
day; this measures the same people's seconds per annotation, with and without
a model's proposals, so the two paths can be compared directly.
"""

from datetime import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.annotations.services import throughput


def _seconds(value: float | None) -> str:
    return "–" if value is None else f"{value:.1f} s"


def _percent(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


class Command(BaseCommand):
    help = "Acceptance and time per decision for each model's proposals, against annotating by hand."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--since", required=True, help="Window start, YYYY-MM-DD.")
        parser.add_argument("--until", help="Window end, YYYY-MM-DD. Defaults to now.")
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")

    def handle(self, *args, **options) -> None:
        since = self._parse(options["since"])
        until = self._parse(options["until"]) if options["until"] else timezone.now()
        if until <= since:
            raise CommandError("--until must be after --since.")

        report = throughput.report(since=since, until=until)
        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2))
            return

        self.stdout.write(
            f"--- proposal throughput, {since.date()} → {until.date()} "
            f"(a gap over {report['session_gap_seconds'] // 60} min is a break) ---"
        )
        if not report["models"]:
            self.stdout.write(self.style.WARNING("No proposals were filed or decided in this window."))
        for model in report["models"]:
            name = " ".join(part for part in (model["task"], model["model_name"] or model["provider"]) if part)
            version = f" @ {model['model_version']}" if model["model_version"] else ""
            decided = model["accepted"] + model["rejected"]
            timing = model["decision_time"]
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(f"{name or '(no ledger row)'}{version}"))
            self.stdout.write(
                f"  filed {model['filed']}: pending {model['pending']}, accepted {model['accepted']} "
                f"({model['accepted_as_filed']} as filed, {model['accepted_corrected']} corrected), "
                f"rejected {model['rejected']}"
            )
            self.stdout.write(
                f"  right as filed: {_percent(model['acceptance_rate'])} of {decided} decided; "
                f"accepted at all: {_percent(model['accepted_rate'])}"
            )
            self.stdout.write(
                f"  corrected: letter {model['corrected_letter']}, box {model['corrected_box']}, "
                f"hand {model['corrected_hand']}"
            )
            self.stdout.write(
                f"  decisions in the window: {timing['actions']}, {timing['timed']} timed, "
                f"{_seconds(timing['mean_seconds'])} mean, {_seconds(timing['median_seconds'])} median; "
                f"{_seconds(model['seconds_per_accepted'])} per annotation made"
            )
            if model["speedup"] is not None:
                self.stdout.write(f"  {model['speedup']:.1f}× the speed of annotating by hand")

        hand = report["by_hand"]
        self.stdout.write("")
        self.stdout.write(
            f"by hand: {hand['actions']} annotations, {hand['timed']} timed, "
            f"{_seconds(hand['mean_seconds'])} mean, {_seconds(hand['median_seconds'])} median"
        )

    @staticmethod
    def _parse(value: str) -> datetime:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"Could not read '{value}' as YYYY-MM-DD.") from None
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

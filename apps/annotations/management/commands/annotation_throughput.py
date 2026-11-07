"""Annotation throughput over a window (AI programme W0.5).

The programme's headline first-year claim is a throughput improvement, which is
worthless without a "before". This measures it — and the reason it has to be
*measured*, rather than derived from the corpus, is that the migrated corpus
carries neither author nor timestamp. Only annotations created through the v3
API leave an `EditEvent`, so only those can be counted.

Run this over a pre-AI window with the actual annotators before W1.1 ships. A
number produced after proposals start arriving is not a baseline.
"""

from collections import defaultdict
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.annotations.models import Graph
from apps.common.models import EditEvent

TARGET_TYPE = "graph"


class Command(BaseCommand):
    help = "Measure annotation throughput per annotator over a window (the pre-AI baseline)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--since", required=True, help="Window start, YYYY-MM-DD.")
        parser.add_argument("--until", help="Window end, YYYY-MM-DD. Defaults to now.")

    def handle(self, *args, **options) -> None:
        since = self._parse(options["since"])
        until = self._parse(options["until"]) if options["until"] else timezone.now()
        if until <= since:
            raise CommandError("--until must be after --since.")

        events = EditEvent.objects.filter(
            target_type=TARGET_TYPE,
            action=EditEvent.Action.CREATED,
            created__gte=since,
            created__lt=until,
        ).values_list("actor__username", "created")

        per_annotator: dict[str, list] = defaultdict(list)
        for username, created in events:
            per_annotator[username or "(unattributed)"].append(created)

        days = max((until - since).days, 1)
        self.stdout.write(f"--- annotation throughput, {since.date()} → {until.date()} ({days} days) ---")

        if not per_annotator:
            self.stdout.write(self.style.WARNING("No annotations created in this window."))
            self._corpus_note()
            return

        width = max(len(name) for name in per_annotator)
        total = 0
        for name, stamps in sorted(per_annotator.items(), key=lambda kv: -len(kv[1])):
            active_days = len({stamp.date() for stamp in stamps})
            total += len(stamps)
            self.stdout.write(
                f"{name:<{width}}  annotations={len(stamps):<6} active_days={active_days:<4} "
                f"per_active_day={len(stamps) / active_days:.1f}"
            )

        active_days_overall = len({stamp.date() for stamps in per_annotator.values() for stamp in stamps})
        self.stdout.write("")
        self.stdout.write(f"total: {total} annotations by {len(per_annotator)} annotators")
        self.stdout.write(f"corpus-wide rate: {total / max(active_days_overall, 1):.1f} per active day")
        self._corpus_note()

    def _corpus_note(self) -> None:
        """State what this number is not, next to the number itself."""
        attributable = EditEvent.objects.filter(target_type=TARGET_TYPE, action=EditEvent.Action.CREATED).count()
        total = Graph.all_objects.count()
        self.stdout.write("")
        self.stdout.write(
            f"Note: {attributable} of {total} annotations in the corpus carry a creation event. "
            "The rest were migrated and have neither author nor timestamp, so they cannot "
            "contribute to a baseline — and the corpus size is not a throughput measurement."
        )

    @staticmethod
    def _parse(value: str) -> datetime:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"Could not read '{value}' as YYYY-MM-DD.") from None
        return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed

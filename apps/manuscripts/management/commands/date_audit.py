"""Corpus-wide dating audit (ROADMAP Track H finding; AI programme W4.1).

Read-only. With --strict it exits non-zero when any dating cannot be true, so it
can gate a release or a training run.

    manage.py date_audit
    manage.py date_audit --strict
"""

from django.core.management.base import BaseCommand

from apps.manuscripts.services import dating


class Command(BaseCommand):
    help = "Report datings that cannot be true, and how many record their provenance."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit non-zero if any dating is internally inconsistent.",
        )
        parser.add_argument("--limit", type=int, default=10, help="Rows to print per problem kind.")

    def handle(self, *args, **options) -> None:
        audit = dating.run()
        limit = options["limit"]

        self.stdout.write("--- corpus datings ---")
        self.stdout.write(f"  {audit.dates} distinct datings across {audit.items_with_a_date} charters")

        kinds = (
            ("inverted", "cannot be true — lower bound after upper"),
            ("unbounded", "no usable numeric bound"),
            ("out_of_era", "outside the corpus's period"),
            ("label_disagrees", "label names years outside the recorded range"),
        )
        for kind, description in kinds:
            found = audit.by_kind(kind)
            if not found:
                continue
            self.stdout.write("")
            self.stdout.write(f"{len(found)} {description}:")
            for problem in found[:limit]:
                self.stdout.write(f"  #{problem.date_id}  {problem.label!r}")
                self.stdout.write(f"      {problem.detail}")
            if len(found) > limit:
                self.stdout.write(f"  … and {len(found) - limit} more (raise --limit to see them)")

        self.stdout.write("")
        self.stdout.write(f"usable as a training label: {audit.usable_for_training} of {audit.dates}")

        # The number that decides whether W4.1 can be done at all.
        self.stdout.write(f"datings recording how they were derived: {audit.provenance_recorded} of {audit.dates}")
        if not audit.provenance_recorded:
            self.stdout.write(
                self.style.WARNING(
                    "  No dating records its provenance, so the charters dated independently of "
                    "their script cannot be told from those dated by reading it. Learning "
                    "date-from-script on this corpus would train on the palaeographer's own "
                    "judgement and then report it back as a discovery. W4.1 is blocked on "
                    "populating HistoricalItemDateAssessment, not on a model."
                )
            )

        broken = audit.by_kind("inverted") + audit.by_kind("unbounded")
        if broken:
            self.stdout.write(self.style.WARNING(f"{len(broken)} datings cannot be used as they stand."))
            if options["strict"]:
                raise SystemExit(1)
        else:
            self.stdout.write(self.style.SUCCESS("Every dating is internally consistent."))

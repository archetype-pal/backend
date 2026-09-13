"""Reproduction-rights clearance, per repository (AI programme W0.4).

Answers, in one command, the question a funder asks at proposal stage and the
question a dataset release has to answer before it ships: do we hold the rights,
and to what? Read-only; with --strict it exits non-zero when anything holding
images is uncleared, so it can gate a release pipeline.
"""

from django.core.management.base import BaseCommand

from apps.manuscripts.services.rights import clearance_summary


class Command(BaseCommand):
    help = "Report reproduction-rights clearance per repository."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit non-zero unless every repository holding images is cleared.",
        )

    def handle(self, *args, **options) -> None:
        rows = clearance_summary()
        if not rows:
            self.stdout.write("No repositories.")
            return

        self.stdout.write("--- reproduction rights by repository ---")
        width = max(len(row.repository) for row in rows)
        for row in sorted(rows, key=lambda r: (r.derivative_release, r.repository)):
            gaps = []
            if not row.has_rights_statement:
                gaps.append("no rights URI")
            if not row.has_attribution:
                gaps.append("no attribution")
            self.stdout.write(
                f"{row.repository:<{width}}  {row.derivative_release:<10}  "
                f"images={row.images:<5} annotated={row.annotated_images:<5}"
                + (f"  [{', '.join(gaps)}]" if gaps else "")
            )
            if row.notes:
                self.stdout.write(f"{'':<{width}}  note: {row.notes}")

        holding = [row for row in rows if row.images]
        uncleared = [row for row in holding if not row.cleared]
        total = sum(row.images for row in rows)
        cleared = sum(row.images for row in rows if row.cleared)

        self.stdout.write("")
        self.stdout.write(f"images cleared for derived-crop redistribution: {cleared} of {total}")
        # Only repositories that actually hold images are a negotiation: the
        # catalogue carries entries with none, and counting those inflates the ask.
        self.stdout.write(f"repositories holding images: {len(holding)} of {len(rows)}")

        if uncleared:
            names = ", ".join(row.repository for row in uncleared)
            self.stdout.write(self.style.WARNING(f"uncleared repositories holding images: {names}"))
            if options["strict"]:
                # Non-zero so a release pipeline stops here rather than
                # publishing pixels nobody has cleared.
                raise SystemExit(1)
        else:
            self.stdout.write(self.style.SUCCESS("every repository holding images is cleared."))

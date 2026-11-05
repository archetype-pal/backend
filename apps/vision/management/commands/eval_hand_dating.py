"""Score how well the hands written most like a charter's date it (AI programme W4.1).

    manage.py eval_hand_dating
    manage.py eval_hand_dating --encoder trocr --neighbours 10

The hands are compared as `compare_hands` compares them. Each dated hand is
guessed to be as old as the mean of its nearest dated hands on other charters,
then on charters held in other repositories, beside the corpus's middle date
and as many hands drawn at random. Nothing is stored.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.vision.services import hand_dating, hand_similarity


class Command(BaseCommand):
    help = "Score how near the dates of a hand's nearest hands come to its charter's date."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--encoder", help=f"Whose vectors to compare the hands by (default {hand_similarity.PART.encoder})."
        )
        parser.add_argument(
            "--neighbours",
            type=int,
            default=hand_dating.NEIGHBOURS,
            help=f"The nearest dated hands a guess is the mean of (default {hand_dating.NEIGHBOURS}).",
        )

    def handle(self, *args, **options) -> None:
        if options["neighbours"] < 1:
            raise CommandError("--neighbours must be at least 1.")
        try:
            part = hand_similarity.part_for(options["encoder"]) if options["encoder"] else hand_similarity.PART
        except ValueError as exc:
            raise CommandError(str(exc)) from None

        comparison = hand_similarity.compare(part)
        dates = hand_dating.catalogue_dates(comparison.hands)
        self.stdout.write(
            f"{comparison.vectors}: {len(comparison.hands)} hands compared, {len(dates)} of them dated; "
            f"each guessed from its {options['neighbours']} nearest dated hands"
        )
        for other_repositories, label in ((False, "on other charters"), (True, "held in other repositories")):
            score = hand_dating.score_dating(
                comparison, dates, neighbours=options["neighbours"], other_repositories=other_repositories
            )
            if score is None:
                self.stdout.write(f"  {label}: no dated hand has a dated hand to compare with; nothing to score")
                continue
            self.stdout.write(
                f"  {label}, {score.hands} hands: off by {score.error:.1f} years on average "
                f"(median {score.median_error:.1f}), {score.within} ({score.within / score.hands:.0%}) within "
                f"{hand_dating.SLACK} years of the catalogue's range, correlation {score.correlation:.2f}; "
                f"the middle date is off by {score.middle_error:.1f}, as many hands at random by "
                f"{score.random_error:.1f}"
            )

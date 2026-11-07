"""Score hand similarity on the scribes the database attributes (AI programme W1.3).

    manage.py eval_hand_similarity
    manage.py eval_hand_similarity --encoder hog --encoder ink --encoder trocr

Each encoder's vectors are compared as `compare_hands` compares them. Then
each hand of an attributed scribe is asked for its nearest hands: how many of
its scribe's other hands are among the ten nearest, where the nearest of them
ranks, and their mean percentile, beside chance. The placeholder scribe is
left out. Nothing is stored.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.vision.services import hand_similarity


class Command(BaseCommand):
    help = "Score how well each encoder's hand similarity finds the hands one scribe wrote."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--encoder",
            action="append",
            help=f"An encoder whose vectors to compare; repeat to compare (default: {hand_similarity.PART.encoder}).",
        )

    def handle(self, *args, **options) -> None:
        try:
            parts = [hand_similarity.part_for(encoder) for encoder in options["encoder"] or []] or [
                hand_similarity.PART
            ]
        except ValueError as exc:
            raise CommandError(str(exc)) from None

        for part in parts:
            comparison = hand_similarity.compare(part)
            self.stdout.write(
                f"{comparison.vectors}: {len(comparison.hands)} hands compared, "
                f"{len(comparison.glyphs) - len(comparison.hands)} with too few glyphs"
            )
            score = hand_similarity.score_attributions(comparison)
            if score is None:
                self.stdout.write("  no attributed scribe has two compared hands; nothing to score")
                continue
            at = hand_similarity.SCORED_AT
            self.stdout.write(f"  {score.scribes} attributed scribe(s) with two or more compared hands: {score.hands}")
            self.stdout.write(
                f"  the scribe's other hands in each hand's {at} nearest: "
                f"{score.found} of {score.possible} (chance {score.by_chance:.1f})"
            )
            self.stdout.write(
                f"  where the nearest of them ranks, per hand: {', '.join(map(str, score.best_ranks))} "
                f"(of {len(comparison.hands) - 1})"
            )
            self.stdout.write(f"  their mean percentile: {score.percentile:.3f} (chance 0.500)")

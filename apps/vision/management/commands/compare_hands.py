"""Compare every hand with every other, letter by letter (AI programme W1.3).

    manage.py compare_hands

Run it after `embed_glyphs --encoder hog`. It reads only stored vectors, calls
no model, and replaces every hand's stored nearest hands.
"""

from django.core.management.base import BaseCommand

from apps.vision.services import hand_similarity


class Command(BaseCommand):
    help = "Find each hand's nearest hands by how alike their letters are."

    def handle(self, *args, **options) -> None:
        tally = hand_similarity.compare_hands()
        self.stdout.write(
            self.style.SUCCESS(
                f"Compared {tally.compared} hands; {tally.too_few_glyphs} had fewer than "
                f"{hand_similarity.MIN_GLYPHS} glyphs with a current vector. Stored {tally.stored} nearest hands."
            )
        )

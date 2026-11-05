"""Score the page search behind conversational annotation (AI programme W3.4).

    manage.py eval_page_search
    manage.py eval_page_search --shown 5 --letters 80

For each of a sample of letters marked on a page by one hand, all but
`--shown` of its examples are hidden and the page is searched by the rest, as
"label every long-s on this folio" searches it. It counts the hidden examples
found among as many proposals as were hidden, and among three times as many.
The pages are annotated in part, so a proposal on an unmarked example of the
letter counts as a miss: the numbers are a lower bound. Nothing is stored.
"""

from django.core.management.base import BaseCommand

from apps.ml.providers.page_search import PageSearchProvider
from apps.vision.services import page_search


def _share(part: int, whole: int) -> str:
    return f"{part} ({part / whole:.0%})"


class Command(BaseCommand):
    help = "Score how many of a page's hidden examples of a letter the W3.4 page search finds again."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--shown", type=int, default=3, help="Examples shown per letter (default 3).")
        parser.add_argument("--letters", type=int, default=40, help="Letters to search (default 40).")
        parser.add_argument("--seed", type=int, default=7, help="Which pages and examples are drawn (default 7).")

    def handle(self, *args, **options) -> None:
        result = page_search.evaluate(shown=options["shown"], letters=options["letters"], seed=options["seed"])
        provider = PageSearchProvider()
        self.stdout.write(
            f"{provider.model_name}@{provider.model_version}: {result.letters} letters on {result.pages} pages, "
            f"{result.shown} examples shown each; {result.unavailable_pages} pages could not be fetched"
        )
        if not result.hidden:
            self.stdout.write("  no letter had enough examples to hide any; nothing to score")
            return
        self.stdout.write(
            f"  of {result.hidden} hidden examples, {_share(result.within_hidden, result.hidden)} were among as many "
            f"proposals as were hidden, {_share(result.within_thrice, result.hidden)} among three times as many "
            f"(by chance {result.by_chance:.1f} and {result.by_chance_thrice:.1f})"
        )
        self.stdout.write(
            "  a lower bound: the pages are annotated in part, and a proposal on an unmarked example counts as a miss"
        )

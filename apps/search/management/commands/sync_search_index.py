"""Management command: sync_search_index <index_type>. Reindex from DB."""

from django.core.management.base import BaseCommand

from apps.search.domain import IndexType
from apps.search.use_cases import ReindexIndex


class Command(BaseCommand):
    help = "Sync a search index from the database (full reindex)."

    def add_arguments(self, parser):
        parser.add_argument(
            "index_type",
            type=str,
            choices=[t.to_url_segment() for t in IndexType],
            help="Index type (e.g. item-parts, item-images, scribes, hands, graphs)",
        )

    def handle(self, *args, **options):
        segment = options["index_type"]
        index_type = IndexType.from_url_segment(segment)
        if index_type is None:
            self.stderr.write(self.style.ERROR(f"Unknown index type: {segment}"))
            return

        use_case = ReindexIndex()
        count = use_case(index_type)
        self.stdout.write(self.style.SUCCESS(f"Indexed {count} documents for {segment}."))

"""Management command: clear_search_index <index_type>. Delete all documents."""

from django.core.management.base import BaseCommand

from apps.search.domain import IndexType
from apps.search.infrastructure.meilisearch_writer import MeilisearchIndexWriter


class Command(BaseCommand):
    help = "Clear a search index (delete all documents)."

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

        writer = MeilisearchIndexWriter()
        writer.delete_all(index_type)
        self.stdout.write(self.style.SUCCESS(f"Cleared index {segment}."))

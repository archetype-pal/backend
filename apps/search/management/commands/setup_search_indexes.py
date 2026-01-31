"""Management command: setup_search_indexes. Create indexes and set settings (no documents)."""

from django.core.management.base import BaseCommand

from apps.search.domain import IndexType
from apps.search.infrastructure.meilisearch_writer import MeilisearchIndexWriter


class Command(BaseCommand):
    help = "Create Meilisearch indexes and set filterable/sortable/searchable attributes (no documents)."

    def handle(self, *args, **options):
        writer = MeilisearchIndexWriter()
        for index_type in IndexType:
            writer.ensure_index_and_settings(index_type)
            self.stdout.write(f"Setup index: {index_type.uid}")
        self.stdout.write(self.style.SUCCESS("Done."))

"""Management command: sync_all_search_indexes. Create all indexes and sync from DB."""

from django.core.management.base import BaseCommand

from apps.search.domain import IndexType
from apps.search.infrastructure.meilisearch_writer import MeilisearchIndexWriter
from apps.search.use_cases import ReindexIndex


class Command(BaseCommand):
    help = "Create all Meilisearch indexes (if missing) and sync each from the database."

    def handle(self, *args, **options):
        writer = MeilisearchIndexWriter()
        reindex = ReindexIndex(writer=writer)

        for index_type in IndexType:
            writer.ensure_index_and_settings(index_type)
            self.stdout.write(f"Setup index: {index_type.uid}")
        self.stdout.write("Indexes created/updated. Syncing from DB...")

        total = 0
        for index_type in IndexType:
            count = reindex(index_type)
            total += count
            self.stdout.write(f"  {index_type.to_url_segment()}: {count} documents")

        self.stdout.write(self.style.SUCCESS(f"Done. Total documents indexed: {total}."))

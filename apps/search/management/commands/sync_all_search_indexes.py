"""Management command: sync_all_search_indexes. Create all indexes and sync from DB."""

from django.core.management.base import BaseCommand

from apps.search.services import IndexingService
from apps.search.types import IndexType


class Command(BaseCommand):
    help = "Create all Meilisearch indexes (if missing) and sync each from the database."

    def handle(self, *args, **options):
        service = IndexingService()
        self.stdout.write("Syncing indexes from DB...")

        total = 0
        for index_type in IndexType:
            count = service.reindex(index_type)
            total += count
            self.stdout.write(f"  {index_type.to_url_segment()}: {count} documents")

        self.stdout.write(self.style.SUCCESS(f"Done. Total documents indexed: {total}."))

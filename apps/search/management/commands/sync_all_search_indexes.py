"""Management command: sync_all_search_indexes. Create all indexes and sync from DB."""

from django.core.management.base import BaseCommand

from apps.search.services import SearchOrchestrationService


class Command(BaseCommand):
    help = "Create all Meilisearch indexes (if missing) and sync each from the database."

    def handle(self, *args, **options):
        self.stdout.write("Syncing indexes from DB...")
        indexed_per_segment = SearchOrchestrationService().reindex_all()
        total = 0
        for segment, count in indexed_per_segment.items():
            total += count
            self.stdout.write(f"  {segment}: {count} documents")

        self.stdout.write(self.style.SUCCESS(f"Done. Total documents indexed: {total}."))

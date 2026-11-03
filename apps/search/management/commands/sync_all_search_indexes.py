from django.core.management.base import BaseCommand, CommandError

from apps.search.services import IndexingService
from apps.search.types import IndexType


class Command(BaseCommand):
    help = "Create all Meilisearch indexes (if missing) and sync each from the database."

    def handle(self, *args, **options):
        self.stdout.write("Syncing indexes from DB...")
        indexed = IndexingService().reindex_all()
        for segment, count in indexed.items():
            self.stdout.write(f"  {segment}: {count} documents")
        # reindex_all logs a failing index and goes on to the next, leaving it out of `indexed`.
        failed = [index_type.segment for index_type in IndexType if index_type.segment not in indexed]
        if failed:
            raise CommandError(f"Reindex failed for {', '.join(failed)}; the log above has the errors.")
        self.stdout.write(self.style.SUCCESS(f"Done. Total documents indexed: {sum(indexed.values())}."))

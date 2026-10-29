from django.core.management.base import BaseCommand

from apps.search.services import IndexingService


class Command(BaseCommand):
    help = "Create all Meilisearch indexes (if missing) and sync each from the database."

    def handle(self, *args, **options):
        self.stdout.write("Syncing indexes from DB...")
        indexed = IndexingService().reindex_all()
        for segment, count in indexed.items():
            self.stdout.write(f"  {segment}: {count} documents")
        self.stdout.write(self.style.SUCCESS(f"Done. Total documents indexed: {sum(indexed.values())}."))

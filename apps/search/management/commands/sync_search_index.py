from django.core.management.base import BaseCommand

from apps.search.services import IndexingService
from apps.search.types import IndexType


class Command(BaseCommand):
    help = "Sync a search index from the database (full reindex)."

    def add_arguments(self, parser):
        parser.add_argument("index_type", choices=[index_type.segment for index_type in IndexType])

    def handle(self, *args, **options):
        segment = options["index_type"]
        count = IndexingService().reindex(IndexType.from_segment(segment))
        self.stdout.write(self.style.SUCCESS(f"Indexed {count} documents for {segment}."))

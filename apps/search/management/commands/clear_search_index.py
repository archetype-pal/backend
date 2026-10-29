from django.core.management.base import BaseCommand

from apps.search.services import IndexingService
from apps.search.types import IndexType


class Command(BaseCommand):
    help = "Clear a search index (delete all documents)."

    def add_arguments(self, parser):
        parser.add_argument("index_type", choices=[index_type.segment for index_type in IndexType])

    def handle(self, *args, **options):
        segment = options["index_type"]
        IndexingService().clear(IndexType.from_segment(segment))
        self.stdout.write(self.style.SUCCESS(f"Cleared index {segment}."))

from django.core.management.base import BaseCommand

from apps.search.services import IndexingService


class Command(BaseCommand):
    help = "Create Meilisearch indexes and set filterable/sortable/searchable attributes (no documents)."

    def handle(self, *args, **options):
        for segment in IndexingService().setup_all():
            self.stdout.write(f"Setup index: {segment}")
        self.stdout.write(self.style.SUCCESS("Done."))

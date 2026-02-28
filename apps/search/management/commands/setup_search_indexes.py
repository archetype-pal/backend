"""Management command: setup_search_indexes. Create indexes and set settings (no documents)."""

from django.core.management.base import BaseCommand

from apps.search.services import SearchOrchestrationService


class Command(BaseCommand):
    help = "Create Meilisearch indexes and set filterable/sortable/searchable attributes (no documents)."

    def handle(self, *args, **options):
        for segment in SearchOrchestrationService().setup_all_indexes():
            self.stdout.write(f"Setup index: {segment}")
        self.stdout.write(self.style.SUCCESS("Done."))

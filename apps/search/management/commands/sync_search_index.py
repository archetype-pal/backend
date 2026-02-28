"""Management command: sync_search_index <index_type>. Reindex from DB."""

from django.core.management.base import BaseCommand

from apps.search.services import SearchOrchestrationService, index_type_segments


class Command(BaseCommand):
    help = "Sync a search index from the database (full reindex)."

    def add_arguments(self, parser):
        parser.add_argument(
            "index_type",
            type=str,
            choices=index_type_segments(),
            help="Index type URL segment.",
        )

    def handle(self, *args, **options):
        segment = options["index_type"]
        try:
            count = SearchOrchestrationService().reindex_index(segment)
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Unknown index type: {segment}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Indexed {count} documents for {segment}."))

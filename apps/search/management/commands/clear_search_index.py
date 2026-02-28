"""Management command: clear_search_index <index_type>. Delete all documents."""

from django.core.management.base import BaseCommand

from apps.search.services import SearchOrchestrationService, index_type_segments


class Command(BaseCommand):
    help = "Clear a search index (delete all documents)."

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
            SearchOrchestrationService().clear_index(segment)
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Unknown index type: {segment}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Cleared index {segment}."))

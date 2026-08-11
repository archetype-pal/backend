"""Delete temp files and rows for upload sessions that never completed.

Run by hand on the API container, e.g.:

    docker compose exec api python manage.py cleanup_stale_uploads
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.uploads.services import cleanup_stale_sessions


class Command(BaseCommand):
    help = "Remove upload sessions (and their temp chunk files) stale for more than --days days."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=settings.UPLOADS_STALE_AFTER_DAYS,
            help="Sessions not modified for this many days are removed (default: UPLOADS_STALE_AFTER_DAYS).",
        )

    def handle(self, *args, **options):
        result = cleanup_stale_sessions(older_than_days=options["days"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {result['sessions']} stale upload session(s) and {result['orphans']} orphan temp dir(s)."
            )
        )

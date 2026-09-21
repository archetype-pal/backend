"""Delete branding/ logo files superseded by a later upload, or never saved.

Run by hand on the API container, e.g.:

    docker compose exec api python manage.py cleanup_orphaned_branding_logos
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.common.services.branding import cleanup_orphaned_branding_logos


class Command(BaseCommand):
    help = "Remove branding/ logo files not referenced by branding.logoUrl, stale for more than --hours hours."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=settings.BRANDING_LOGO_STALE_AFTER_HOURS,
            help="Files older than this many hours are removed (default: BRANDING_LOGO_STALE_AFTER_HOURS).",
        )

    def handle(self, *args, **options):
        result = cleanup_orphaned_branding_logos(older_than_hours=options["hours"])
        self.stdout.write(self.style.SUCCESS(f"Removed {result['removed']} orphaned branding logo file(s)."))

"""Delete tutor sessions past their retention, with their pictures. Run it daily."""

from django.core.management.base import BaseCommand

from apps.learn.services import retention


class Command(BaseCommand):
    help = "Delete tutor sessions older than LEARN_RETENTION_DAYS with their pictures, and close stale ones."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count what would go, delete nothing.")

    def handle(self, *args, dry_run: bool = False, **options):
        if dry_run:
            self.stdout.write(
                f"Would delete {retention.expired().count()} sessions and close {retention.stale().count()} stale ones."
            )
            return
        pruned = retention.prune()
        self.stdout.write(f"Deleted {pruned.deleted} sessions and closed {pruned.closed} stale ones.")

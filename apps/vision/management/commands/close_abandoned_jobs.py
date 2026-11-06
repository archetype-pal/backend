from django.core.management.base import BaseCommand

from apps.ml.services import ledger
from apps.vision.services import page_drafts, page_letters


class Command(BaseCommand):
    help = "Close model calls and page requests whose worker stopped without finishing."

    def handle(self, *args, **options):
        jobs = ledger.close_abandoned()
        requests = page_drafts.close_abandoned() + page_letters.close_abandoned()
        self.stdout.write(f"Closed {jobs} jobs and {requests} page requests.")

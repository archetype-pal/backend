"""Reap old rows out of the soft-delete trash.

`SoftDeleteModel` never frees a row on its own, so without this the trash grows
without bound and every `objects` read pays for it in the index scan. Purging is
a real `.delete()`, so the same invariants a manual purge relies on still hold:
`pre_delete` strips dangling references and `post_delete` records an EditEvent.

Dry-run unless `--apply`, matching `embed_annotation_ids`.

Models are discovered rather than listed: anything inheriting `SoftDeleteModel`
is reaped, so a second soft-deletable model does not need a second command.
"""

from datetime import timedelta

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.models import SoftDeleteModel


def _soft_delete_models() -> list[type[SoftDeleteModel]]:
    return sorted(
        (m for m in django_apps.get_models() if issubclass(m, SoftDeleteModel)),
        key=lambda m: m._meta.label,
    )


class Command(BaseCommand):
    help = "Permanently delete trashed rows older than --older-than days."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--older-than",
            dest="older_than",
            type=int,
            required=True,
            help="Purge rows trashed at least this many days ago. 0 purges the whole trash.",
        )
        parser.add_argument(
            "--model",
            dest="model_label",
            type=str,
            default=None,
            help="Restrict to one model, as app_label.ModelName (default: every soft-deletable model).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without it the command only reports what it would delete.",
        )

    def handle(self, *args, **options) -> None:
        older_than = options["older_than"]
        if older_than < 0:
            raise CommandError("--older-than must be 0 or more.")

        models = _soft_delete_models()
        if options["model_label"]:
            models = [self._one_model(options["model_label"], models)]

        cutoff = timezone.now() - timedelta(days=older_than)
        apply_changes = options["apply"]
        total = 0

        self.stdout.write(f"--- trash purge (trashed on or before {cutoff.isoformat()}) ---")
        for model in models:
            queryset = model.all_objects.trashed().filter(deleted_at__lte=cutoff)
            count = queryset.count()
            total += count
            if count and apply_changes:
                # One transaction per model so a failure on the second model
                # cannot half-purge the first.
                with transaction.atomic():
                    queryset.delete()
            self.stdout.write(f"{model._meta.label}: {count}")

        if not total:
            self.stdout.write(self.style.SUCCESS("Nothing to purge."))
            return
        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Purged {total} row(s). This cannot be undone."))
        else:
            self.stdout.write(self.style.WARNING(f"Dry run: {total} row(s) would be purged. Re-run with --apply."))

    def _one_model(self, label: str, models: list[type[SoftDeleteModel]]) -> type[SoftDeleteModel]:
        for model in models:
            if model._meta.label.lower() == label.lower():
                return model
        known = ", ".join(m._meta.label for m in models) or "none"
        raise CommandError(f"{label} is not a soft-deletable model. Known: {known}.")

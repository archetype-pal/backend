from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.common.legacy_migration_importer import (
    PHASE_ORDER,
    ImportOptions,
    LegacyMigrationImportError,
    render_import_report_json,
    run_import,
)


class Command(BaseCommand):
    help = "Safely import supported legacy source data into a freshly migrated target database."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--legacy-url",
            default=None,
            help=(
                "Legacy PostgreSQL URL. Defaults to LEGACY_DATABASE_URL, or a database named by "
                "LEGACY_DATABASE_NAME derived from --target-url, TARGET_DATABASE_URL, or DATABASE_URL."
            ),
        )
        parser.add_argument(
            "--target-url",
            default=None,
            help=(
                "Target PostgreSQL URL. Defaults to TARGET_DATABASE_URL, DATABASE_URL, or a compose-style "
                "URL from TARGET_DATABASE_NAME/POSTGRES_DB and POSTGRES_* env."
            ),
        )
        parser.add_argument(
            "--phase",
            action="append",
            choices=("all", *PHASE_ORDER),
            default=None,
            help="Import phase to run. Repeat for multiple phases. Default: all.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually write to the target database. Without this flag the command only plans the import.",
        )
        parser.add_argument(
            "--allow-non-empty-target",
            action="store_true",
            help="Allow writes when import target tables already contain rows. Use only for approved recovery work.",
        )
        parser.add_argument(
            "--allow-warnings",
            action="store_true",
            help="Allow post-import audit warnings after they have been recorded in the manifest.",
        )
        parser.add_argument(
            "--skip-post-audit",
            action="store_true",
            help="Skip the post-import audit. Intended only for partial phase testing.",
        )
        parser.add_argument(
            "--publication-author-id",
            type=int,
            default=None,
            help="Target auth_user.id to assign to imported publications.",
        )
        parser.add_argument(
            "--publication-author-username",
            default=None,
            help="Target auth_user.username to assign to imported publications.",
        )
        parser.add_argument(
            "--manifest",
            type=Path,
            default=None,
            help="Optional JSON output path for the import report.",
        )

    def handle(self, *args, **options) -> None:
        import_options = ImportOptions(
            legacy_url=options["legacy_url"],
            target_url=options["target_url"],
            phases=tuple(options["phase"] or ("all",)),
            execute=options["execute"],
            allow_non_empty_target=options["allow_non_empty_target"],
            allow_warnings=options["allow_warnings"],
            publication_author_id=options["publication_author_id"],
            publication_author_username=options["publication_author_username"],
            skip_post_audit=options["skip_post_audit"],
            manifest_path=options["manifest"],
        )
        try:
            report = run_import(import_options)
        except LegacyMigrationImportError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(render_import_report_json(report))
        if report.dry_run:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --execute to write data."))
        elif report.status == "ok":
            self.stdout.write(self.style.SUCCESS("Legacy data import completed."))
        else:
            self.stdout.write(self.style.WARNING(f"Legacy data import completed with status: {report.status}"))

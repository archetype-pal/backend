from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.common.legacy_migration_audit import (
    LegacyMigrationAuditError,
    legacy_url_from_env,
    render_json,
    render_markdown,
    run_audit,
    target_url_from_env,
)


class Command(BaseCommand):
    help = "Read-only audit of legacy old_arch data against the current Archetype schema."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--legacy-url",
            default=legacy_url_from_env(),
            help="Legacy PostgreSQL URL. Defaults to LEGACY_DATABASE_URL or old_arch on the compose postgres host.",
        )
        parser.add_argument(
            "--target-url",
            default=target_url_from_env(),
            help="Target PostgreSQL URL. Defaults to TARGET_DATABASE_URL or test_db on the compose postgres host.",
        )
        parser.add_argument(
            "--format",
            choices=("markdown", "json"),
            default="markdown",
            help="Output format.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            help="Optional output file path. Writes to stdout when omitted.",
        )
        parser.add_argument(
            "--fail-on-warning",
            action="store_true",
            help="Exit non-zero when the audit has warnings as well as hard failures.",
        )

    def handle(self, *args, **options) -> None:
        try:
            report = run_audit(legacy_url=options["legacy_url"], target_url=options["target_url"])
        except LegacyMigrationAuditError as exc:
            raise CommandError(str(exc)) from exc

        rendered = render_json(report) if options["format"] == "json" else render_markdown(report)

        output_path = options.get("output")
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote legacy migration audit to {output_path}"))
        else:
            self.stdout.write(rendered)

        if report.status == "fail" or (report.status == "warn" and options["fail_on_warning"]):
            raise CommandError(f"Legacy migration audit completed with status: {report.status}")

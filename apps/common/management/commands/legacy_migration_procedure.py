from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.common.legacy_migration_audit import (
    LegacyMigrationAuditError,
    legacy_url_from_env,
    run_audit,
    target_url_from_env,
)
from apps.common.legacy_migration_procedure import (
    render_manifest_template,
    render_procedure_json,
    render_procedure_markdown,
)


class Command(BaseCommand):
    help = "Render the legacy migration operator guide and manifest template."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--legacy-url",
            default=None,
            help=(
                "Legacy PostgreSQL URL. Used only with --with-live-audit. Defaults to LEGACY_DATABASE_URL, "
                "or old_arch derived from --target-url, TARGET_DATABASE_URL, or DATABASE_URL."
            ),
        )
        parser.add_argument(
            "--target-url",
            default=None,
            help=(
                "Target PostgreSQL URL. Used only with --with-live-audit. Defaults to TARGET_DATABASE_URL, "
                "DATABASE_URL, or a compose-style test_db URL from POSTGRES_* env."
            ),
        )
        parser.add_argument(
            "--with-live-audit",
            action="store_true",
            help="Run the read-only audit and include its summary in the guide/manifest.",
        )
        parser.add_argument(
            "--format",
            choices=("markdown", "json"),
            default="markdown",
            help="Guide output format.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            help="Optional guide output file path. Writes to stdout when omitted.",
        )
        parser.add_argument(
            "--manifest-template",
            type=Path,
            help="Optional path for a JSON migration manifest template.",
        )
        parser.add_argument(
            "--fail-on-audit-failure",
            action="store_true",
            help="Exit non-zero when --with-live-audit returns fail status.",
        )

    def handle(self, *args, **options) -> None:
        audit_report = None
        if options["with_live_audit"]:
            target_url = options["target_url"] or target_url_from_env()
            legacy_url = options["legacy_url"] or legacy_url_from_env(base_url=target_url)
            try:
                audit_report = run_audit(legacy_url=legacy_url, target_url=target_url)
            except LegacyMigrationAuditError as exc:
                raise CommandError(str(exc)) from exc

        rendered = (
            render_procedure_json(audit_report)
            if options["format"] == "json"
            else render_procedure_markdown(audit_report)
        )

        output_path = options.get("output")
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote legacy migration procedure to {output_path}"))
        else:
            self.stdout.write(rendered)

        manifest_path = options.get("manifest_template")
        if manifest_path:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(render_manifest_template(audit_report), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Wrote legacy migration manifest template to {manifest_path}"))

        if audit_report and audit_report.status == "fail" and options["fail_on_audit_failure"]:
            raise CommandError("Legacy migration procedure live audit completed with status: fail")

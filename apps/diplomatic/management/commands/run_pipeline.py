"""Run one AI pipeline over the corpus, or show what it would send.

The operator surface for Phase 2. Deliberately a command rather than an HTTP
endpoint: these runs are long, expensive and corpus-wide, and a request path
that starts one is a request path that can start a thousand.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.diplomatic import services
from apps.diplomatic.pipelines.base import PIPELINE_REGISTRY, UnknownPipeline


class Command(BaseCommand):
    help = "Run a registered AI pipeline and file its output as proposals for review."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("pipeline", nargs="?", default="", help="Pipeline key, e.g. W2.1.")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many units.")
        parser.add_argument("--provider", default=services.DEFAULT_PROVIDER)
        parser.add_argument("--model", default=None, help="Override the provider's default model.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Render prompts and call no model. Free, and the only safe way to read a new prompt.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        key = options["pipeline"]
        if not key:
            self.stdout.write("Registered pipelines:")
            for pipeline in sorted(PIPELINE_REGISTRY.values(), key=lambda p: p.key):
                self.stdout.write(f"  {pipeline.key:<8} {pipeline.description}")
            return

        try:
            tally = services.run(
                key,
                limit=options["limit"],
                provider=options["provider"],
                model=options["model"],
                dry_run=options["dry_run"],
            )
        except UnknownPipeline as exc:
            raise CommandError(str(exc)) from exc

        for name, count in tally.items():
            self.stdout.write(f"{name}: {count}")
        if tally["refused"]:
            # A refusal is a cap or the data-policy gate, not a transient error.
            # Saying so here saves an operator from re-running into the same wall.
            self.stdout.write(self.style.WARNING("Refused: a spend cap or the hosted-provider gate stopped the run."))
        if tally["proposed"]:
            self.stdout.write(
                self.style.SUCCESS(f"{tally['proposed']} proposals await review; nothing has entered the record.")
            )

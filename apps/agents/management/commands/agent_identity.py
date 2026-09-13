"""Create or inspect a scoped service identity.

An identity is a credential, so it is provisioned deliberately rather than
appearing on first use. Two defaults are load-bearing: a new identity is
**disabled**, and its allow-list is **empty**. Both mean a mistake here fails
closed — the agent answers nothing — rather than granting the corpus to
whatever the last argument happened to say.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.agents import tools
from apps.agents.models import ServiceIdentity

# What the public agent gets: read the corpus, look at the annotated regions,
# cite what it found. Everything that could become a write path is absent, and
# so is every tool that cannot answer yet.
PUBLIC_TOOLS = ["search_charters", "get_charter", "get_image_regions", "cite_record"]
# Granted from the start although they cannot answer yet. The allow-list is a
# statement of scope; `unavailable()` is a statement of readiness, and keeping
# them separate means enabling W2.1's output is not also a permissions change.
FUTURE_TOOLS = ["fetch_witnesses", "fetch_relations", "compare_hands"]


class Command(BaseCommand):
    help = "Create, update or show an agent service identity."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("slug", nargs="?", default="", help="Identity slug; omit to list all.")
        parser.add_argument("--create", action="store_true", help="Create it if it does not exist.")
        parser.add_argument("--public-tools", action="store_true", help="Grant the public allow-list.")
        parser.add_argument("--tools", default="", help="Comma-separated tool names to grant.")
        parser.add_argument("--quota", type=int, default=None, help="Daily runs per requester.")
        parser.add_argument("--max-turns", type=int, default=None)
        parser.add_argument("--model", default=None, help="Provider model slug.")
        parser.add_argument("--enable", action="store_true")
        parser.add_argument("--disable", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        slug = options["slug"]
        if not slug:
            for identity in ServiceIdentity.objects.all():
                state = "enabled" if identity.enabled else "disabled"
                self.stdout.write(f"{identity.slug} ({state}): {', '.join(identity.allowed_tools) or 'no tools'}")
            self.stdout.write("\nRegistered tools:")
            for name, tool in sorted(tools.TOOL_REGISTRY.items()):
                reason = tool.unavailable()
                self.stdout.write(f"  {name:<20} {reason or 'available'}")
            return

        identity = ServiceIdentity.objects.filter(slug=slug).first()
        if identity is None:
            if not options["create"]:
                raise CommandError(f"No identity '{slug}'. Pass --create to make one.")
            identity = ServiceIdentity(slug=slug, description="", allowed_tools=[], enabled=False)

        granted = list(identity.allowed_tools or [])
        if options["public_tools"]:
            granted = PUBLIC_TOOLS + FUTURE_TOOLS
        if options["tools"]:
            granted = [name.strip() for name in options["tools"].split(",") if name.strip()]

        unknown = [name for name in granted if name not in tools.TOOL_REGISTRY]
        if unknown:
            raise CommandError(f"Unknown tools: {', '.join(unknown)}.")
        identity.allowed_tools = granted

        if options["quota"] is not None:
            identity.daily_run_quota = options["quota"]
        if options["max_turns"] is not None:
            identity.max_turns = options["max_turns"]
        if options["model"] is not None:
            identity.model_name = options["model"]
        if options["enable"]:
            identity.enabled = True
        if options["disable"]:
            identity.enabled = False
        identity.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"{identity.slug}: {'enabled' if identity.enabled else 'disabled'}, "
                f"{identity.daily_run_quota}/day, {identity.max_turns} turns"
            )
        )
        for name in identity.allowed_tools:
            reason = tools.TOOL_REGISTRY[name].unavailable()
            self.stdout.write(f"  {name:<20} {reason or 'available'}")

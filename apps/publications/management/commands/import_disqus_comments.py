from datetime import UTC, datetime
from html import escape, unescape
import json
import re
from urllib.parse import parse_qs, urlparse

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.publications.models import Comment, Publication

DISQUS_REDIRECT_HREF = re.compile(r'href="(https?://disq\.us/url\?[^"]+)"')


def unwrap_disqus_links(html: str) -> str:
    def real_href(match: re.Match[str]) -> str:
        targets = parse_qs(urlparse(unescape(match.group(1))).query).get("url")
        if not targets:
            return match.group(0)
        return f'href="{escape(targets[0].rsplit(":", 1)[0])}"'

    return DISQUS_REDIRECT_HREF.sub(real_href, html)


def _posts_worth_keeping(posts: list[dict]) -> set[str]:
    """Ids of the posts to import: every shown post, and each deleted one that still
    has a shown post somewhere below it (it becomes a placeholder holding that
    reply's place). A deleted post with nothing shown below would be a placeholder
    nobody can see or remove."""
    by_id = {post["id"]: post for post in posts}
    kept: set[str] = set()
    for post in posts:
        if post["deleted"]:
            continue
        node: dict | None = post
        while node is not None and node["id"] not in kept:
            kept.add(node["id"])
            node = by_id.get(str(node["parent"])) if node["parent"] else None
    return kept


class Command(BaseCommand):
    help = "Import comments from a Disqus snapshot, matching thread BlogPost-<id> to publication <id>."

    def add_arguments(self, parser) -> None:
        parser.add_argument("snapshot", help="JSON file of Disqus threads, each with identifier, title and posts.")
        parser.add_argument("--apply", action="store_true", help="Write the comments (dry run otherwise).")

    def handle(self, *args, **options) -> None:
        apply_changes = bool(options.get("apply"))
        with open(options["snapshot"], encoding="utf-8") as fh:
            threads = json.load(fh)

        self.stdout.write(f"Running in {'APPLY' if apply_changes else 'DRY-RUN'} mode.")
        summary = {"created": 0, "already_imported": 0, "skipped_deleted": 0, "threads_without_publication": 0}
        with transaction.atomic():
            for thread in threads.values():
                self._import_thread(thread, summary)
            if not apply_changes:
                transaction.set_rollback(True)
        self.stdout.write(", ".join(f"{key}={value}" for key, value in summary.items()))

    def _import_thread(self, thread: dict, summary: dict[str, int]) -> None:
        publication_id = int(thread["identifier"].removeprefix("BlogPost-"))
        publication = Publication.objects.filter(pk=publication_id).first()
        target = f"{publication.pk:>5} {publication.title[:40]}" if publication else "  missing"
        self.stdout.write(f"{thread['identifier']:<14} {unescape(thread['title'])[:40]:<40} -> {target}")
        if publication is None:
            summary["threads_without_publication"] += 1
            return

        imported: dict[str, Comment] = {}
        kept = _posts_worth_keeping(thread["posts"])
        for post in sorted(thread["posts"], key=lambda item: item["createdAt"]):
            if post["id"] not in kept:
                summary["skipped_deleted"] += 1
                continue
            deleted = post["deleted"]
            comment, created = Comment.objects.get_or_create(
                disqus_id=post["id"],
                defaults={
                    "post": publication,
                    "parent": imported.get(str(post["parent"])),
                    "author_name": "" if deleted else post["name"],
                    "content": "" if deleted else unwrap_disqus_links(post["html"]),
                    "is_approved": not deleted,
                    "is_deleted": deleted,
                },
            )
            if created:
                created_at = datetime.fromisoformat(post["createdAt"]).replace(tzinfo=UTC)
                Comment.objects.filter(pk=comment.pk).update(created_at=created_at)
            summary["created" if created else "already_imported"] += 1
            imported[post["id"]] = comment

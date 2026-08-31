"""Lay out stored TEI so the backoffice Source view is readable.

The corpus arrived from the migration as one unbroken line per text — 862 of
899 rows contain no newline at all. `format_tei` re-wraps them without touching
a character of the transcription (see its module docstring for the rule it
holds to, and `test_tei_format.py` for the invariant).

Reports what it would change and exits; pass `--apply` to write. Every row is
re-checked after formatting and skipped if the character data moved, so a bug
here cannot reach the database.
"""

import re
import xml.etree.ElementTree as ET

from django.core.management.base import BaseCommand

from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import format_tei, validate_tei_wellformed


def _paragraph_text(content: str) -> list[str] | None:
    """Character data per top-level element, whitespace collapsed.

    The comparison the formatter must survive: whitespace may move between
    paragraphs, never within one. None when the fragment will not parse.
    """
    try:
        root = ET.fromstring(f"<r>{content}</r>")
    except ET.ParseError:
        return None
    return [re.sub(r"\s+", " ", "".join(node.itertext())).strip() for node in root]


class Command(BaseCommand):
    help = "Reformat ImageText.content for readability. Dry run unless --apply is given."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run).")
        parser.add_argument(
            "--id", type=int, action="append", dest="ids", help="Limit to this ImageText id (repeatable)."
        )
        parser.add_argument("--width", type=int, default=100, help="Wrap column (default: 100).")

    def handle(self, *args, **options) -> None:
        queryset = ImageText.objects.all().only("id", "content").order_by("id")
        if options["ids"]:
            queryset = queryset.filter(id__in=options["ids"])

        scanned = changed = skipped_invalid = skipped_unsafe = 0
        for text in queryset:
            content = text.content or ""
            if not content.strip():
                continue
            scanned += 1
            if validate_tei_wellformed(content):
                skipped_invalid += 1
                self.stdout.write(f"  ! {text.id}: not well-formed, left alone")
                continue

            formatted = format_tei(content, width=options["width"])
            if formatted == content:
                continue

            before = _paragraph_text(content)
            if before is None or _paragraph_text(formatted) != before:
                skipped_unsafe += 1
                self.stdout.write(self.style.ERROR(f"  ! {text.id}: formatting altered the text, left alone"))
                continue

            changed += 1
            if options["apply"]:
                text.content = formatted
                text.save(update_fields=["content"])

        verb = "reformatted" if options["apply"] else "would reformat"
        self.stdout.write(f"scanned: {scanned}")
        self.stdout.write(f"{verb}: {changed}")
        if skipped_invalid:
            self.stdout.write(f"skipped (not well-formed): {skipped_invalid}")
        if skipped_unsafe:
            self.stdout.write(self.style.ERROR(f"skipped (unsafe): {skipped_unsafe}"))
        if not options["apply"] and changed:
            self.stdout.write(self.style.WARNING("Dry run — re-run with --apply to write."))

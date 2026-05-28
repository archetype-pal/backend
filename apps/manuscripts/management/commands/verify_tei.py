"""Corpus-wide TEI well-formedness gate.

Validates every `ImageText.content` as well-formed XML and exits non-zero if
any row fails. Used as the safety gate at the end of a backup migration (and
usable in CI). Rows still in legacy `data-dpt` form fail here (HTML entities
like `&nbsp;` are not valid XML), so this also surfaces any row the
TEI migration could not convert.
"""

from django.core.management.base import BaseCommand

from apps.manuscripts.models import ImageText
from apps.manuscripts.services.tei import validate_tei_wellformed


class Command(BaseCommand):
    help = "Verify every ImageText.content is well-formed TEI XML; non-zero exit on failure."

    def handle(self, *args, **options) -> None:
        total = 0
        invalid: list[tuple[int, str]] = []
        for it in ImageText.objects.all().only("id", "content"):
            total += 1
            errors = validate_tei_wellformed(it.content or "")
            if errors:
                invalid.append((it.id, errors[0]["message"]))

        self.stdout.write(f"checked: {total}")
        self.stdout.write(f"invalid: {len(invalid)}")
        if invalid:
            for fid, msg in invalid[:100]:
                self.stdout.write(f"  ImageText #{fid}: {msg}")
            if len(invalid) > 100:
                self.stdout.write(f"  ... and {len(invalid) - 100} more")
            self.stderr.write(f"FAILED: {len(invalid)} row(s) are not well-formed TEI XML.")
            raise SystemExit(1)
        self.stdout.write("All ImageText.content is well-formed TEI XML.")

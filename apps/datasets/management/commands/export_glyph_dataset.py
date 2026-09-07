"""Build the pixel-free glyph dataset release (AI programme W0.2).

The programme's earliest citable output: it needs no rights clearance, and it is
useful to other projects whether or not the rest of the programme ships.

    manage.py export_glyph_dataset --out storage/releases --version v1
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.datasets.export import (
    LICENSE_NOTICE,
    build_manifest,
    build_splits,
    class_support,
    collect_glyphs,
    unlocated,
)


class Command(BaseCommand):
    help = "Export the pixel-free glyph dataset (geometry, labels and IIIF region references)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--out", required=True, help="Directory to write the release into.")
        parser.add_argument("--release", default="v1", help="Release version, recorded in the manifest.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite an existing release directory of the same version.",
        )
        parser.add_argument(
            "--allow-unlocated",
            action="store_true",
            help="Publish even if some regions could not be located (they ship as null).",
        )

    def handle(self, *args, **options) -> None:
        destination = Path(options["out"]) / options["release"]
        if destination.exists() and not options["force"]:
            # A published version is frozen by its DOI; overwriting one silently
            # would make the citation point at different data than it did.
            raise CommandError(f"{destination} already exists. Pass --force to overwrite.")
        destination.mkdir(parents=True, exist_ok=True)

        self.stdout.write("Collecting glyph annotations…")
        rows = collect_glyphs()
        if not rows:
            raise CommandError("No glyph annotations found — nothing to export.")

        missing = unlocated(rows)
        if missing and not options["allow_unlocated"]:
            # A region computed without its page height is mirrored, and a DOI
            # freezes whatever ships. Refuse rather than publish a guess.
            raise CommandError(
                f"{len(missing)} of {len(rows)} glyphs have no locatable IIIF region — their image "
                "height could not be read from the image server, and a region derived without it "
                "would be vertically mirrored. Fix the image server, or pass --allow-unlocated to "
                "publish those rows with a null region."
            )

        splits = build_splits(rows)
        manifest = build_manifest(rows, splits, version=options["release"])

        with (destination / "glyphs.jsonl").open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row.as_dict(), separators=(",", ":")) + "\n")

        self._write_json(destination / "allographs.json", class_support(rows))
        self._write_json(
            destination / "splits.json",
            {"by_charter": splits.by_charter, "by_repository": splits.by_repository},
        )
        self._write_json(destination / "manifest.json", manifest)
        (destination / "LICENSE.txt").write_text(LICENSE_NOTICE, encoding="utf-8")

        counts = manifest["counts"]
        self.stdout.write("")
        self.stdout.write(f"Wrote {destination}")
        if missing:
            self.stdout.write(
                self.style.WARNING(f"  {len(missing)} glyphs shipped with a null region (--allow-unlocated)")
            )
        self.stdout.write(
            f"  {counts['glyphs']} glyphs · {counts['charters']} charters · "
            f"{counts['images']} images · {counts['allograph_classes']} classes"
        )
        thin = [entry for entry in class_support(rows) if entry["thin"]]
        if thin:
            self.stdout.write(
                self.style.WARNING(f"  {len(thin)} classes have fewer than 20 examples — flagged in allographs.json")
            )
        rights = manifest["rights"]
        self.stdout.write(
            f"  contains no pixels; {rights['images_cleared_for_crop_redistribution']} of "
            f"{rights['images_total']} images would be cleared for a crop release"
        )
        self.stdout.write(self.style.SUCCESS("Pixel-free release complete — no clearance required."))

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")

"""
Management command to update all ItemImage records to use random images from a directory.

This command will:
1. Recursively find all image files in the given directory (default: storage/media/opal_plus)
2. For each ItemImage, assign a randomly chosen image from that directory
"""

from pathlib import Path
import random

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.manuscripts.models import ItemImage

# Common image extensions to look for
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}


def get_media_root() -> Path:
    """Resolve the absolute MEDIA_ROOT path."""
    if hasattr(settings, "MEDIA_ROOT") and settings.MEDIA_ROOT:
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_absolute():
            media_root = Path(settings.BASE_DIR) / media_root
        return media_root

    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    return backend_dir / "storage" / "media"


def get_default_images_dir() -> Path | None:
    """Resolve the default images directory (opal_plus)."""
    media_root = get_media_root()
    for subdir in ("opal_plus", "sipi"):
        candidate = media_root / subdir
        if candidate.exists():
            return candidate
    return None


def find_image_files(directory: Path) -> list[Path]:
    """Recursively find all image files in a directory, excluding metadata files."""
    image_files = []
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and ":Zone.Identifier" not in path.name:
            image_files.append(path)
    return sorted(image_files, key=lambda p: p.name)


class Command(BaseCommand):
    help = "Update all ItemImage records to use random images from a directory"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--images-dir",
            type=str,
            help="Path to the images directory (default: <MEDIA_ROOT>/opal_plus)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        images_dir = options.get("images_dir")

        if images_dir:
            images_dir = Path(images_dir)
            if not images_dir.is_dir():
                self.stdout.write(self.style.ERROR(f"Images directory not found: {images_dir}"))
                return
        else:
            images_dir = get_default_images_dir()
            if not images_dir:
                self.stdout.write(
                    self.style.ERROR(
                        "Could not find default images directory. "
                        "Use --images-dir or ensure MEDIA_ROOT/opal_plus exists."
                    )
                )
                return

        # Recursively find all image files
        image_files = find_image_files(images_dir)

        if not image_files:
            self.stdout.write(self.style.ERROR(f"No image files (e.g. .jpg, .png) found in {images_dir}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(image_files)} image(s) in {images_dir} (recursive)"))
        for f in image_files:
            rel = f.relative_to(images_dir)
            self.stdout.write(f"  - {rel}")

        item_images = list(ItemImage.objects.all())
        total = len(item_images)

        if total == 0:
            self.stdout.write(self.style.WARNING("No ItemImage records found in the database"))
            return

        self.stdout.write(f"\nFound {total} ItemImage record(s) to update")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN MODE - No changes will be made\n"))

        media_root = get_media_root()

        def to_media_path(path: Path) -> str:
            """Compute path relative to MEDIA_ROOT for the IIIFField / Sipi."""
            try:
                relative_path = path.relative_to(media_root)
                return str(relative_path).replace("\\", "/")
            except ValueError:
                return path.name

        updated = 0
        for item_image in item_images:
            chosen = random.choice(image_files)
            image_path = to_media_path(chosen)

            if dry_run:
                self.stdout.write(f"Would set ItemImage id={item_image.id} ({item_image}) -> {image_path}")
            else:
                item_image.image = image_path
                item_image.save()
                updated += 1
                if updated % 10 == 0 or updated == total:
                    self.stdout.write(f"Updated {updated}/{total} ItemImage records...")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nUpdated {updated} ItemImage record(s)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nWould update {total} ItemImage record(s)"))

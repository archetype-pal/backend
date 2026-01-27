"""
Management command to update all ItemImage records to use random images from storage/media/sipi.

This command will:
1. Find all image files in storage/media/sipi
2. For each ItemImage, assign a randomly chosen image from that directory
"""

import random
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.manuscripts.models import ItemImage

# Common image extensions to look for
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}


def get_images_dir():
    """Resolve the storage/media/sipi directory."""
    if hasattr(settings, "MEDIA_ROOT") and settings.MEDIA_ROOT:
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_absolute():
            media_root = Path(settings.BASE_DIR) / media_root
        images_dir = media_root / "sipi"
        if images_dir.exists():
            return images_dir

    # Fallback: relative to backend (e.g. when running from backend/)
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    for base in (backend_dir, backend_dir.parent):
        cand = base / "storage" / "media" / "sipi"
        if cand.exists():
            return cand

    return None


class Command(BaseCommand):
    help = "Update all ItemImage records to use random images from storage/media/sipi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--images-dir",
            type=str,
            help="Path to the images directory (default: <MEDIA_ROOT>/sipi or storage/media/sipi)",
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
            images_dir = get_images_dir()
            if not images_dir:
                self.stdout.write(
                    self.style.ERROR(
                        "Could not find storage/media/sipi. Set --images-dir or ensure MEDIA_ROOT/sipi exists."
                    )
                )
                return

        # Find all image files
        image_files = [
            f
            for f in images_dir.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
        ]

        if not image_files:
            self.stdout.write(
                self.style.ERROR(
                    f"No image files (e.g. .jpg, .png) found in {images_dir}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Found {len(image_files)} image(s) in {images_dir}")
        )
        for f in sorted(image_files, key=lambda p: p.name):
            self.stdout.write(f"  - {f.name}")

        item_images = list(ItemImage.objects.all())
        total = len(item_images)

        if total == 0:
            self.stdout.write(self.style.WARNING("No ItemImage records found in the database"))
            return

        self.stdout.write(f"\nFound {total} ItemImage record(s) to update")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN MODE - No changes will be made\n"))

        # Get MEDIA_ROOT to compute relative paths
        if hasattr(settings, "MEDIA_ROOT") and settings.MEDIA_ROOT:
            media_root = Path(settings.MEDIA_ROOT)
            if not media_root.is_absolute():
                media_root = Path(settings.BASE_DIR) / media_root
        else:
            # Fallback
            backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
            media_root = backend_dir / "storage" / "media"

        # Path relative to MEDIA_ROOT for IIIFField
        # Note: Paths should be relative to Sipi's mount point (/sipi/images)
        # So 'scans/file.jpg' not 'sipi/scans/file.jpg'
        def to_media_path(path: Path) -> str:
            try:
                # Compute relative path from MEDIA_ROOT to the image file
                relative_path = path.relative_to(media_root)
                path_str = str(relative_path).replace("\\", "/")  # Normalize path separators
                # Remove 'sipi/' prefix if present, as Sipi expects paths relative to /sipi/images
                if path_str.startswith('sipi/'):
                    path_str = path_str.replace('sipi/', '', 1)
                return path_str
            except ValueError:
                # If path is not under MEDIA_ROOT, fall back to old behavior
                # Check if images_dir contains "scans" subdirectory
                if "scans" in str(images_dir):
                    return f"scans/{path.name}"
                return path.name

        updated = 0
        for item_image in item_images:
            chosen = random.choice(image_files)
            image_path = to_media_path(chosen)

            if dry_run:
                self.stdout.write(
                    f"Would set ItemImage id={item_image.id} ({item_image}) -> {image_path}"
                )
            else:
                item_image.image = image_path
                item_image.save()
                updated += 1
                if updated % 10 == 0 or updated == total:
                    self.stdout.write(f"Updated {updated}/{total} ItemImage records...")

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"\nUpdated {updated} ItemImage record(s)"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nWould update {total} ItemImage record(s)"))

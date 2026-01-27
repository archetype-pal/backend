"""
Management command to update CarouselItem records to use images from storage/media/carousel.

This command will:
1. Find all image files in storage/media/carousel
2. For each CarouselItem, assign an image (cycling through if there are more items than images)
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.publications.models import CarouselItem

# Common image extensions to look for
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff"}


def get_carousel_dir():
    """Resolve the storage/media/carousel directory."""
    if hasattr(settings, "MEDIA_ROOT") and settings.MEDIA_ROOT:
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.is_absolute():
            media_root = Path(settings.BASE_DIR) / media_root
        carousel_dir = media_root / "carousel"
        if carousel_dir.exists():
            return carousel_dir

    # Fallback: relative to backend (e.g. when running from backend/)
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    for base in (backend_dir, backend_dir.parent):
        cand = base / "storage" / "media" / "carousel"
        if cand.exists():
            return cand

    return None


class Command(BaseCommand):
    help = "Update all CarouselItem records to use images from storage/media/carousel"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--carousel-dir",
            type=str,
            help="Path to the carousel directory (default: <MEDIA_ROOT>/carousel or storage/media/carousel)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        carousel_dir = options.get("carousel_dir")

        if carousel_dir:
            carousel_dir = Path(carousel_dir)
            if not carousel_dir.is_dir():
                self.stdout.write(self.style.ERROR(f"Carousel directory not found: {carousel_dir}"))
                return
        else:
            carousel_dir = get_carousel_dir()
            if not carousel_dir:
                self.stdout.write(
                    self.style.ERROR(
                        "Could not find storage/media/carousel. Set --carousel-dir or ensure MEDIA_ROOT/carousel exists."
                    )
                )
                return

        # Find all image files (excluding the duplicate kelso_image_o21YxfU.jpg)
        carousel_images = [
            f
            for f in carousel_dir.iterdir()
            if f.is_file()
            and f.suffix.lower() in IMAGE_EXTENSIONS
            and not f.name.startswith("kelso_image_o21YxfU")  # Exclude duplicate
        ]

        if not carousel_images:
            self.stdout.write(
                self.style.ERROR(
                    f"No image files found in {carousel_dir}"
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Found {len(carousel_images)} image(s) in {carousel_dir}")
        )
        for f in sorted(carousel_images, key=lambda p: p.name):
            self.stdout.write(f"  - {f.name}")

        carousel_items = list(CarouselItem.objects.all().order_by("ordering", "id"))
        total = len(carousel_items)

        if total == 0:
            self.stdout.write(self.style.WARNING("No CarouselItem records found in the database"))
            return

        self.stdout.write(f"\nFound {total} CarouselItem record(s) to update")

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

        # Path relative to MEDIA_ROOT for ImageField
        def to_media_path(path: Path) -> str:
            try:
                # Compute relative path from MEDIA_ROOT to the image file
                relative_path = path.relative_to(media_root)
                return str(relative_path).replace("\\", "/")  # Normalize path separators
            except ValueError:
                # If path is not under MEDIA_ROOT, fall back to just the filename
                return f"carousel/{path.name}"

        # Map carousel items to images based on their titles/ordering
        # Match images to items based on the original website mapping
        image_mapping = {
            "About Models of Authority": "kelso_image.jpg",
            "Browsing images of the charters": "browse.jpg",
            "Results of a search": "search.jpg",
            "Annotating a charter": "annotating.jpg",
            "The text viewer showing an edited version of a charter alongside its translation": "editing.jpg",
            'Search results for allograph "d" in charters from the National Library of Scotland': "allographs.jpg",
            "Add your favourite manuscripts and graphs to a personal Collection": "collections.jpg",
            "One of the many seals soon to be available in the Models of Authority database": "seal.jpg",
        }

        updated = 0
        for carousel_item in carousel_items:
            # Try to find matching image by title, otherwise cycle through available images
            matched_image = None
            if carousel_item.title in image_mapping:
                image_name = image_mapping[carousel_item.title]
                matched_image = next((img for img in carousel_images if img.name == image_name), None)

            if not matched_image:
                # Fall back to cycling through images
                idx = carousel_items.index(carousel_item)
                matched_image = carousel_images[idx % len(carousel_images)]

            image_path = to_media_path(matched_image)

            if dry_run:
                self.stdout.write(
                    f"Would set CarouselItem id={carousel_item.id} ({carousel_item.title}) -> {image_path}"
                )
            else:
                carousel_item.image = image_path
                carousel_item.save()
                updated += 1
                if updated % 5 == 0 or updated == total:
                    self.stdout.write(f"Updated {updated}/{total} CarouselItem records...")

        if not dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"\nUpdated {updated} CarouselItem record(s)"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nWould update {total} CarouselItem record(s)"))

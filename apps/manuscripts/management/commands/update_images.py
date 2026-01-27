"""
Management command to update all ItemImage records to use .tif files from storage/media.

This command will:
1. Find all .tif files in the storage/media directory
2. Update all ItemImage records to use these files
3. Distribute the images across all ItemImage records (cycling if there are more records than files)
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.manuscripts.models import ItemImage


class Command(BaseCommand):
    help = "Update all ItemImage records to use .tif files from storage/media"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--media-path",
            type=str,
            help="Path to media directory (default: infrastructure/storage/media)",
        )
        parser.add_argument(
            "--use-upload-to",
            action="store_true",
            help="Use the upload_to path format (historical_items/filename.tif) instead of just filename",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        media_path = options.get("media_path")
        use_upload_to = options.get("use_upload_to", False)

        # Determine the media path
        if media_path:
            media_dir = Path(media_path)
        else:
            # Try to find the media directory
            # Check if we're in the infrastructure directory context
            base_dir = Path(__file__).parent.parent.parent.parent.parent.parent
            media_dir = base_dir / "infrastructure" / "storage" / "media"

            # If that doesn't exist, try relative to backend
            if not media_dir.exists():
                backend_dir = Path(__file__).parent.parent.parent.parent.parent
                media_dir = backend_dir.parent / "infrastructure" / "storage" / "media"

            # Fallback to MEDIA_ROOT from settings if available
            if not media_dir.exists() and hasattr(settings, "MEDIA_ROOT"):
                media_dir = Path(settings.MEDIA_ROOT)
                if not media_dir.is_absolute():
                    # If relative, make it relative to BASE_DIR
                    base_dir = Path(settings.BASE_DIR)
                    media_dir = base_dir / media_dir

        if not media_dir.exists():
            self.stdout.write(self.style.ERROR(f"Media directory not found: {media_dir}"))
            return

        # Find all .tif files
        tif_files = sorted(media_dir.glob("*.tif"))

        if not tif_files:
            self.stdout.write(self.style.ERROR(f"No .tif files found in {media_dir}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(tif_files)} .tif files in {media_dir}"))
        for tif_file in tif_files:
            self.stdout.write(f"  - {tif_file.name}")

        # Get all ItemImage records
        item_images = ItemImage.objects.all()
        total_images = item_images.count()

        if total_images == 0:
            self.stdout.write(self.style.WARNING("No ItemImage records found in the database"))
            return

        self.stdout.write(f"\nFound {total_images} ItemImage records to update")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDRY RUN MODE - No changes will be made\n"))

        # Update each ItemImage record
        updated_count = 0
        for idx, item_image in enumerate(item_images):
            # Cycle through the .tif files if there are more records than files
            tif_file = tif_files[idx % len(tif_files)]

            # Get the relative path from MEDIA_ROOT
            # IIIFField stores the path relative to MEDIA_ROOT
            # Since MEDIA_ROOT is "storage/media/" and upload_to is "historical_items",
            # we can use either:
            # - Just the filename (if files are directly in media/ and Sipi looks there)
            # - "historical_items/filename.tif" (if Django expects the upload_to path)
            if use_upload_to:
                image_path = f"historical_items/{tif_file.name}"
            else:
                image_path = tif_file.name

            if dry_run:
                self.stdout.write(f"Would update ItemImage {item_image.id} ({item_image}) to use {image_path}")
            else:
                item_image.image = image_path
                item_image.save()
                updated_count += 1

                if (updated_count % 10 == 0) or (updated_count == total_images):
                    self.stdout.write(f"Updated {updated_count}/{total_images} ItemImage records...")

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"\nSuccessfully updated {updated_count} ItemImage records"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nWould update {total_images} ItemImage records"))

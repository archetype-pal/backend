"""Application services for manuscripts app workflows."""

from pathlib import Path
from typing import Any

from apps.manuscripts.iiif import get_iiif_url

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".tif")


def build_image_picker_payload(*, media_root: str, relative_path: str) -> dict[str, list[dict[str, Any]]]:
    """Return folder/image payload used by the management image picker."""
    media_dir = Path(media_root) / relative_path
    folders: list[dict[str, str]] = []
    images: list[dict[str, str]] = []

    if media_dir.exists():
        for item in sorted(media_dir.iterdir(), key=lambda p: p.name.lower()):
            item_relative = str(Path(relative_path) / item.name) if relative_path else item.name
            if item.is_dir():
                folders.append({"name": item.name, "path": item_relative})
            elif item.name.lower().endswith(_IMAGE_EXTENSIONS):
                images.append({"name": item.name, "path": item_relative, "url": get_iiif_url(item_relative)})

    return {"folders": folders, "images": images}


def optimize_item_part_public_queryset(queryset: Any) -> Any:
    return queryset.select_related("historical_item", "current_item")


def optimize_historical_item_management_queryset(queryset: Any, *, action: str | None) -> Any:
    if action == "list":
        return queryset.select_related("date", "format").prefetch_related(
            "catalogue_numbers__catalogue",
            "itempart_set__current_item__repository",
            "itempart_set__images",
        )
    if action == "retrieve":
        return queryset.select_related("date", "format").prefetch_related(
            "catalogue_numbers__catalogue",
            "descriptions__source",
            "itempart_set__current_item__repository",
            "itempart_set__images__texts",
        )
    return queryset

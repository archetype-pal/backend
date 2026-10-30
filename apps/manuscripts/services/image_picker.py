"""Folder/image listings for the backoffice image picker (IIIF paths from the database, filesystem fallback)."""

from pathlib import Path

from apps.manuscripts.models import ItemImage
from apps.manuscripts.services.iiif import get_iiif_url

_IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".jp2")


def build_image_picker_payload(*, media_root: str, relative_path: str) -> dict[str, list[dict[str, str]]]:
    """Return folder/image payload used by the management image picker."""
    root: Path = Path(media_root).resolve()
    media_dir: Path = (root / relative_path).resolve()

    if not media_dir.is_relative_to(root):
        return {"folders": [], "images": []}

    folders: list[dict[str, str]] = []
    images: list[dict[str, str]] = []

    if media_dir.exists():
        for item in sorted(media_dir.iterdir(), key=lambda p: p.name.lower()):
            item_relative: str = str(Path(relative_path) / item.name) if relative_path else item.name
            if item.is_dir():
                folders.append({"name": item.name, "path": item_relative})
            elif item.name.lower().endswith(_IMAGE_EXTENSIONS):
                images.append({"name": item.name, "path": item_relative, "url": get_iiif_url(item_relative)})

    return {"folders": folders, "images": images}


def build_iiif_image_picker_payload(relative_path: str) -> dict[str, list[dict[str, str]]]:
    """Browse IIIF image paths stored in the database, grouped by folder prefix."""
    prefix = relative_path.rstrip("/") + "/" if relative_path else ""
    paths = ItemImage.objects.exclude(image="").values_list("image", flat=True).distinct()

    folder_set: set[str] = set()
    images: list[dict[str, str]] = []

    for raw_path in paths:
        p = str(raw_path)
        if prefix and not p.startswith(prefix):
            continue
        remainder = p[len(prefix) :]
        if "/" in remainder:
            folder_name = remainder.split("/", 1)[0]
            folder_set.add(folder_name)
        else:
            iiif_url = get_iiif_url(p)
            images.append({"name": remainder, "path": p, "url": iiif_url})

    folders = sorted(
        [{"name": f, "path": f"{prefix}{f}" if prefix else f} for f in folder_set],
        key=lambda x: x["name"].lower(),
    )
    images.sort(key=lambda x: x["name"].lower())
    return {"folders": folders, "images": images}

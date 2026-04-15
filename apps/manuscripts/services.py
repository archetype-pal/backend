"""Application services for manuscripts app workflows."""

import logging
from pathlib import Path
from typing import Any

from django.db.models import Count, Prefetch, QuerySet

from apps.manuscripts.iiif import get_iiif_url
from apps.manuscripts.models import HistoricalItem, ItemImage

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".gif", ".tif")


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


def optimize_historical_item_management_queryset(
    queryset: QuerySet[HistoricalItem], *, action: str | None
) -> QuerySet[HistoricalItem]:
    if action == "list":
        return (
            queryset.select_related("date", "format")
            .prefetch_related(
                "catalogue_numbers__catalogue",
                "itempart_set__current_item__repository",
            )
            .annotate(
                part_count=Count("itempart", distinct=True),
                image_count=Count("itempart__images", distinct=True),
            )
        )
    if action == "retrieve":
        return queryset.select_related("date", "format").prefetch_related(
            "catalogue_numbers__catalogue",
            "descriptions__source",
        )
    return queryset


def build_item_parts_detail(historical_item: HistoricalItem) -> list[dict[str, Any]]:
    """Build the nested item_parts payload for the HistoricalItem detail endpoint."""
    parts = historical_item.itempart_set.select_related("current_item__repository").prefetch_related(
        Prefetch(
            "images",
            queryset=ItemImage.objects.annotate(text_count=Count("texts")),
        ),
    )
    result: list[dict[str, Any]] = []
    for part in parts:
        images: list[dict[str, Any]] = []
        for img in part.images.all():
            iiif_url: str | None = None
            if img.image:
                try:
                    iiif_url = img.image.iiif.identifier
                except (AttributeError, TypeError, ValueError) as exc:
                    logger.debug("IIIF identifier unavailable for image %s: %s", img.id, exc)
                    iiif_url = str(img.image)
            images.append(
                {
                    "id": img.id,
                    "image": iiif_url,
                    "locus": img.locus,
                    "text_count": img.text_count,
                }
            )
        current_item = part.current_item
        result.append(
            {
                "id": part.id,
                "custom_label": part.custom_label,
                "current_item": part.current_item_id,
                "current_item_display": str(current_item) if current_item else None,
                "current_item_locus": part.current_item_locus,
                "display_label": part.display_label(),
                "repository": current_item.repository_id if current_item else None,
                "repository_name": current_item.repository.label if current_item and current_item.repository else None,
                "shelfmark": current_item.shelfmark if current_item else None,
                "images": images,
            }
        )
    return result

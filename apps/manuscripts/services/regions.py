"""Turning stored annotation rings into IIIF regions, correctly.

The stored rings are Y-up (origin bottom-left, a DigiPal inheritance) and IIIF
is Y-down, so converting one without the page's pixel height mirrors it about
the vertical midline — silently, and plausibly enough to survive review. That
bug shipped once in the dataset export; the fix belongs here, where every
caller can reach it, rather than in each caller.

`_fetch_info_dimensions` is used rather than the public
`resolve_image_dimensions` precisely because it *raises*: the public helper
falls back to a 1000px default, and a confidently wrong coordinate is worse
than a missing one.
"""

from concurrent.futures import ThreadPoolExecutor
import logging

from apps.manuscripts.iiif import _fetch_info_dimensions, get_iiif_region_from_geojson
from apps.manuscripts.models import ItemImage

logger = logging.getLogger(__name__)


def _safe_dimensions(identifier: str) -> tuple[int, int] | None:
    try:
        return _fetch_info_dimensions(identifier)
    except (OSError, ValueError, KeyError, TypeError):  # fmt: skip
        logger.warning("Could not resolve IIIF dimensions for %s", identifier)
        return None


def heights_for(image_ids: set[int]) -> tuple[dict[int, int], list[int]]:
    """Resolve each image's pixel height. Returns `(heights, unresolved_ids)`."""
    identifiers: dict[int, str | None] = {}
    for image in ItemImage.objects.filter(id__in=image_ids).only("id", "image"):
        try:
            identifiers[image.id] = image.image.iiif.identifier
        except (AttributeError, TypeError, ValueError):  # fmt: skip
            identifiers[image.id] = None

    distinct = sorted({identifier for identifier in identifiers.values() if identifier})
    resolved: dict[str, int] = {}
    if distinct:
        # Concurrently: a cold cache over N images otherwise costs N serial
        # three-second timeouts.
        with ThreadPoolExecutor(max_workers=min(8, len(distinct))) as pool:
            for identifier, dims in zip(distinct, pool.map(_safe_dimensions, distinct), strict=True):
                if dims is not None:
                    resolved[identifier] = dims[1]

    heights: dict[int, int] = {}
    unresolved: list[int] = []
    for image_id, image_identifier in identifiers.items():
        height = resolved.get(image_identifier) if image_identifier else None
        if height:
            heights[image_id] = height
        else:
            unresolved.append(image_id)
    return heights, unresolved


def region_for(annotation: str | dict, image_id: int, heights: dict[int, int]) -> str | None:
    """The IIIF region for one annotation, or None when the height is unknown.

    None rather than a guess: a citation that points at the wrong half of the
    page is the failure §8.3 exists to prevent, and it looks exactly like a
    correct one.
    """
    height = heights.get(image_id)
    if not height:
        return None
    region = get_iiif_region_from_geojson(annotation, image_height=height)  # type: ignore[arg-type]
    return None if region == "full" else region

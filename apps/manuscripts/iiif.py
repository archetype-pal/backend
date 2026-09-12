from functools import lru_cache
import json
import logging
import time
from urllib.parse import urljoin
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

# Fallback canvas size when an image's info.json can't be fetched. The Y-flip
# computed against this is only approximate, so callers should treat a fallback
# as "dimensions unknown".
FALLBACK_IMAGE_DIMS = (1000, 1000)

# A single slow SIPI response shouldn't be enough to silently mis-render a
# canvas at the wrong aspect ratio: retry transient (network/timeout) failures
# once, a beat later, before giving up. Malformed responses (bad JSON, missing
# width/height) are not retried — a second attempt against the same broken
# response can't help.
_FETCH_RETRIES = 2
_FETCH_TIMEOUT_SECONDS = 5
_RETRY_DELAY_SECONDS = 0.5


def _internal_info_json_url(identifier: str) -> str:
    """The identifier's info.json URL, resolved against IIIF_INTERNAL_HOST
    instead of the public IIIF_HOST baked into it. `identifier` is built for
    *browsers* (Mirador, `<img>` tags) — when this process (running inside the
    api/celery container) needs to reach the image server itself, IIIF_HOST
    is frequently unreachable (e.g. `localhost` resolves to the calling
    container, not SIPI's), which is exactly what IIIF_INTERNAL_HOST exists
    to route around. A no-op when the two hosts are the same."""
    public_host = settings.IIIF_HOST.rstrip("/")
    internal_host = settings.IIIF_INTERNAL_HOST.rstrip("/")
    if internal_host == public_host or not identifier.startswith(public_host):
        return f"{identifier}/info.json"
    return f"{internal_host}{identifier[len(public_host):]}/info.json"


@lru_cache(maxsize=4096)
def _fetch_info_dimensions(identifier: str) -> tuple[int, int]:
    """(width, height) from the image's info.json. Raises on any failure so
    that only *successful* lookups are memoized (failures must not be cached)."""
    url = _internal_info_json_url(identifier)
    last_error: OSError | None = None
    for attempt in range(_FETCH_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
                info = json.loads(resp.read())
            return int(info["width"]), int(info["height"])
        except OSError as exc:
            last_error = exc
            if attempt + 1 < _FETCH_RETRIES:
                time.sleep(_RETRY_DELAY_SECONDS)
    assert last_error is not None  # fmt: skip
    raise last_error


def resolve_image_dimensions(identifier: str) -> tuple[int, int]:
    """(width, height) for an IIIF image identifier; falls back without caching
    the failure, so a recovered image server is re-probed on the next call."""
    try:
        return _fetch_info_dimensions(identifier)
    except (OSError, ValueError, KeyError, TypeError) as exc:  # fmt: skip
        logger.warning(
            "Falling back to %sx%s dimensions for IIIF image %r after %s retries: %s",
            FALLBACK_IMAGE_DIMS[0],
            FALLBACK_IMAGE_DIMS[1],
            identifier,
            _FETCH_RETRIES,
            exc,
        )
        return FALLBACK_IMAGE_DIMS


def get_iiif_url(file_path: str, profile_name: str | None = None) -> str:
    """
    Helper function to join parts of a URL for IIIF.
    """
    profile_name = profile_name or list(settings.IIIF_PROFILES.keys())[0]

    iiif_profile = settings.IIIF_PROFILES.get(profile_name, None)
    if not iiif_profile:
        raise ValueError(f"Profile '{profile_name}' not found in IIIF_PROFILES.")
    iiif_path = file_path.replace("/", "%2F")
    iiif_path += f"/{iiif_profile['region']}/{iiif_profile['size']}/{iiif_profile['rotation']}"
    iiif_path += f"/{iiif_profile['quality']}.{iiif_profile['format']}"
    return str(urljoin(iiif_profile["host"], iiif_path))


def get_iiif_region_from_geojson(coordinates_json: str, image_height: int | None = None) -> str:
    """
    Extract bounding box from GeoJSON coordinates and convert to IIIF region format.

    Args:
        coordinates_json: JSON string containing GeoJSON Feature with Polygon geometry
        image_height: Optional full image height in pixels. When provided, Y values
            are flipped from legacy bottom-left origin to IIIF top-left origin.

    Returns:
        IIIF region string in format "x,y,w,h"
    """
    try:
        if isinstance(coordinates_json, str):
            coords_data = json.loads(coordinates_json)
        else:
            coords_data = coordinates_json

        # Handle both Feature and direct geometry formats
        if coords_data.get("type") == "Feature":
            geometry = coords_data.get("geometry", {})
        else:
            geometry = coords_data

        if geometry.get("type") != "Polygon":
            return "full"

        # Get the first ring of the polygon (outer ring)
        polygon_coords = geometry.get("coordinates", [])
        if not polygon_coords or not polygon_coords[0]:
            return "full"

        ring = polygon_coords[0]

        # Extract x and y coordinates
        x_coords = [point[0] for point in ring]
        y_coords = [point[1] for point in ring]

        # Calculate bounding box
        min_x = min(x_coords)
        min_y = min(y_coords)
        max_x = max(x_coords)
        max_y = max(y_coords)

        # Calculate width and height
        width = max_x - min_x
        height = max_y - min_y

        # Legacy graph coordinates are Y-up (origin at bottom-left). IIIF is Y-down.
        if image_height is not None:
            min_y = image_height - min_y - height

        # Convert to integers (IIIF typically uses integer coordinates)
        x = int(min_x)
        y = int(min_y)
        w = max(1, int(width))
        h = max(1, int(height))

        return f"{x},{y},{w},{h}"
    except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError):  # fmt: skip
        # If parsing fails, return "full" to show the entire image
        return "full"

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
import logging
import time
from typing import Any
from urllib.parse import urljoin
import urllib.request

from django.conf import settings
from djiiif import IIIFFieldFile

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
    return f"{internal_host}{identifier[len(public_host) :]}/info.json"


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
    return str(urljoin(settings.IIIF_HOST, iiif_path))


def resolve_dimensions_for(
    images: Sequence[Any],
    dims: Callable[[str], tuple[int, int]] = resolve_image_dimensions,
) -> list[tuple[str | None, tuple[int, int]]]:
    """``(identifier, (width, height))`` for each ItemImage, in order.

    Distinct identifiers are resolved concurrently, so a cold cache over an
    N-image part costs about one timeout rather than N serial ones. An image
    with no resolvable identifier gets ``FALLBACK_IMAGE_DIMS``. ``dims`` is
    injectable so callers' tests can stub the image server.
    """
    identifiers = [item_image_identifier(image) for image in images]
    distinct = sorted({identifier for identifier in identifiers if identifier})
    resolved: dict[str, tuple[int, int]] = {}
    if distinct:
        with ThreadPoolExecutor(max_workers=min(8, len(distinct))) as pool:
            resolved = dict(zip(distinct, pool.map(dims, distinct), strict=True))
    return [
        (identifier, resolved.get(identifier, FALLBACK_IMAGE_DIMS) if identifier else FALLBACK_IMAGE_DIMS)
        for identifier in identifiers
    ]


def _iiif_identifier(image: IIIFFieldFile) -> str | None:
    try:
        return str(image.iiif.identifier)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("IIIF identifier unavailable for %s: %s", image, exc)
        return None


def get_image_identifier(image: IIIFFieldFile | None) -> str | None:
    """The IIIF identifier for an image field file, or ``None`` when unset.

    This is the only form the image server is addressable by: ``IIIF_HOST``
    plus the percent-encoded storage path. It is NOT interchangeable with the
    bare storage path — wherever ``IIIF_HOST`` carries a path prefix (a
    deployment serving the image server under ``/sipi``, say), that prefix is
    part of the identifier and a bare path resolves nowhere.

    Falls back to the bare storage path when the identifier cannot be built,
    so a management screen still shows *which* file a row points at; use
    `item_image_identifier` where only a real identifier will do.
    """
    if not image:
        return None
    identifier = _iiif_identifier(image)
    return identifier if identifier is not None else str(image)


def item_image_identifier(item_image: Any) -> str | None:
    """The IIIF identifier of an ItemImage row, or ``None`` when it cannot be resolved.

    Strict counterpart of `get_image_identifier`: the IIIF/W3C publishers
    must never address the image server by a bare path.
    """
    image = getattr(item_image, "image", None)
    if not image:
        return None
    return _iiif_identifier(image)


def get_iiif_region_from_geojson(coordinates_json: str, image_height: int | None = None) -> str:
    """Bounding box of a GeoJSON Polygon (Feature or bare geometry) as an IIIF `x,y,w,h` region.

    `image_height` flips legacy Y-up (bottom-left origin) coordinates to IIIF's
    Y-down. Anything unparseable yields `"full"`, so a bad region shows the
    whole image rather than an error.
    """
    try:
        data = json.loads(coordinates_json) if isinstance(coordinates_json, str) else coordinates_json
        geometry = data.get("geometry", {}) if data.get("type") == "Feature" else data
        if geometry.get("type") != "Polygon":
            return "full"
        ring = geometry["coordinates"][0]
        xs = [point[0] for point in ring]
        ys = [point[1] for point in ring]
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        min_y = image_height - min(ys) - height if image_height is not None else min(ys)
        return f"{int(min(xs))},{int(min_y)},{max(1, int(width))},{max(1, int(height))}"
    except (AttributeError, json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError):  # fmt: skip
        return "full"

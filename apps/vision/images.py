"""Getting a page in front of a model, and its geometry back out again.

Two problems, both of which have bitten this codebase before.

**The picture has to travel.** A hosted model needs a URL it can reach or the
bytes inline. Our IIIF server is not on the public internet in every
deployment, and an image URL that resolves for us and not for the model fails
as an empty answer rather than an error — so the bytes are inlined as a
`data:` URL, fetched through the same IIIF endpoint the site uses.

**The coordinates have to come back correctly.** Stored annotation rings are
Y-up, a DigiPal inheritance; every image coordinate system a model will use is
Y-down. Converting between them without the page height mirrors the box about
the horizontal midline — and a mirrored box on a page of text looks entirely
plausible. Nothing here guesses a height: when it cannot be resolved, the
proposal is not made.
"""

import base64
import logging
from typing import Any
import urllib.request

from apps.manuscripts.iiif import _fetch_info_dimensions
from apps.manuscripts.models import ItemImage

logger = logging.getLogger(__name__)

# Long edge, in pixels, of the rendition sent to the model. Big enough for a
# 12th-century charter hand to be legible, small enough that a corpus pass is
# not priced by the megapixel.
RENDITION = 1600
# Refuse anything larger rather than send it. A page that arrives bigger than
# this is a configuration problem, and discovering it on an invoice is worse
# than discovering it here.
MAX_BYTES = 12 * 1024 * 1024
TIMEOUT = 20


class ImageUnavailable(Exception):
    """The page could not be fetched, or its dimensions are unknown."""


def identifier(image: ItemImage) -> str:
    try:
        return str(image.image.iiif.identifier)
    except (AttributeError, TypeError, ValueError) as exc:  # fmt: skip
        raise ImageUnavailable(f"Image {image.pk} has no IIIF identifier.") from exc


def dimensions(image: ItemImage) -> tuple[int, int]:
    """(width, height) in pixels, or raise.

    Uses the raising helper rather than `resolve_image_dimensions`, which falls
    back to 1000×1000 — a silent fallback here would mirror every box it
    produced.
    """
    try:
        return _fetch_info_dimensions(identifier(image))
    except ImageUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:  # fmt: skip
        raise ImageUnavailable(f"Could not resolve dimensions for image {image.pk}: {exc}") from exc


def data_url(image: ItemImage, *, size: int = RENDITION) -> str:
    """The page as an inline `data:` URL, at a bounded size."""
    url = f"{identifier(image)}/full/!{size},{size}/0/default.jpg"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            payload = response.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ImageUnavailable(f"Could not fetch image {image.pk}: {exc}") from exc
    if not payload:
        raise ImageUnavailable(f"Image {image.pk} returned no data.")
    if len(payload) > MAX_BYTES:
        raise ImageUnavailable(f"Image {image.pk} is larger than {MAX_BYTES} bytes; not sending it.")
    return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")


def ring_from_box(box: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    """A model's normalised box → the Y-up GeoJSON ring the platform stores.

    `box` carries `x`, `y`, `w`, `h` as fractions of the page, with the origin
    at the top left — the convention every vision model uses. The stored ring
    puts the origin at the bottom left, so `y` is flipped here rather than at
    read time, and the annotation is indistinguishable from a hand-drawn one.
    """
    left = float(box["x"]) * width
    top = float(box["y"]) * height
    box_width = float(box["w"]) * width
    box_height = float(box["h"]) * height

    lower = height - (top + box_height)
    upper = height - top
    right = left + box_width

    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [round(left), round(lower)],
                    [round(right), round(lower)],
                    [round(right), round(upper)],
                    [round(left), round(upper)],
                    [round(left), round(lower)],
                ]
            ],
        },
    }


def plausible(box: dict[str, Any]) -> bool:
    """Reject a box before it becomes a proposal a human has to read.

    A glyph is a small fraction of a charter. A box covering a third of the page
    is the model having found the text block rather than a letter, and a
    zero-width one is arithmetic that went wrong. Neither is worth a reviewer's
    attention, and both are cheap to catch.
    """
    try:
        x, y, w, h = (float(box[key]) for key in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):  # fmt: skip
        return False
    if not (0.0 <= x < 1.0 and 0.0 <= y < 1.0):
        return False
    if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0):
        return False
    if x + w > 1.001 or y + h > 1.001:
        return False
    return w * h <= 0.05

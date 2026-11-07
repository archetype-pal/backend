"""The picture a lesson is about, and the closer looks the tutor takes at it.

Every box in a lesson is in the pixels of one picture, stored with its
session: the tutor is shown that picture, its crops are cut from it, and the
student's page draws on it. A corpus page is the image server's rendition at
the size the model reads best; a student's own picture is checked, turned
upright and brought to the same size.
"""

import base64
from dataclasses import dataclass
import io
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from apps.manuscripts.models import ItemImage
from apps.vision import images

# The longer side the current Claude models read without scaling the picture down.
LONGEST_SIDE = 2576
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# A picture bigger than this many pixels is refused before it is decoded: a
# small file can unpack into gigabytes.
MAX_UPLOAD_PIXELS = 80_000_000
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "TIFF"}
# A closer look is enlarged until its longer side is this long, but never more
# than `MAX_ENLARGEMENT` times: past that, nothing new is visible.
CLOSER_LOOK_SIDE = 1400
MAX_ENLARGEMENT = 4.0
SMALLEST_LOOK = 8
JPEG_QUALITY = 90


class PictureRefused(ValueError):
    """The picture cannot be used. The message is safe to show the student."""


@dataclass(frozen=True)
class Picture:
    jpeg: bytes
    width: int
    height: int


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def from_upload(data: bytes) -> Picture:
    """A student's picture, checked, turned upright, and at most `LONGEST_SIDE` a side."""
    if not data:
        raise PictureRefused("The picture is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PictureRefused(f"The picture is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ACCEPTED_FORMATS:
                raise PictureRefused("Send a JPEG, PNG, WebP or TIFF picture.")
            if probe.width * probe.height > MAX_UPLOAD_PIXELS:
                raise PictureRefused("The picture has too many pixels; send a smaller one.")
            probe.load()
            image = ImageOps.exif_transpose(probe).convert("RGB")
    except PictureRefused:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise PictureRefused("The file is not a picture that can be read.") from exc
    image.thumbnail((LONGEST_SIDE, LONGEST_SIDE), Image.Resampling.LANCZOS)
    return Picture(_jpeg(image), image.width, image.height)


def from_page(page: ItemImage) -> Picture:
    """A corpus page as the image server renders it, at most `LONGEST_SIDE` a side.

    Raises `images.ImageUnavailable` when the page cannot be fetched.
    """
    url = images.data_url(page, size=LONGEST_SIDE)
    data = base64.b64decode(url.partition("base64,")[2])
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise images.ImageUnavailable(f"Image {page.pk} did not come back as a picture.") from exc
    return Picture(data, width, height)


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


def clamp(box: dict[str, Any], *, width: int, height: int) -> dict[str, int] | None:
    """`box` (`x`, `y`, `width`, `height` in pixels) kept inside the picture, or None if nothing is left."""
    try:
        x, y = round(float(box["x"])), round(float(box["y"]))
        right, bottom = x + round(float(box["width"])), y + round(float(box["height"]))
    except (KeyError, TypeError, ValueError):  # fmt: skip
        return None
    x, y = max(0, min(x, width)), max(0, min(y, height))
    right, bottom = max(0, min(right, width)), max(0, min(bottom, height))
    if right - x < 1 or bottom - y < 1:
        return None
    return {"x": x, "y": y, "width": right - x, "height": bottom - y}


def closer_look(jpeg: bytes, box: dict[str, int]) -> tuple[bytes, float]:
    """The region `box` of the picture, enlarged, and by how much."""
    with Image.open(io.BytesIO(jpeg)) as image:
        region = image.convert("RGB").crop(
            (
                box["x"],
                box["y"],
                box["x"] + max(box["width"], SMALLEST_LOOK),
                box["y"] + max(box["height"], SMALLEST_LOOK),
            )
        )
    scale = min(MAX_ENLARGEMENT, CLOSER_LOOK_SIDE / max(region.width, region.height))
    scale = max(scale, 1.0)
    if scale > 1.0:
        region = region.resize((round(region.width * scale), round(region.height * scale)), Image.Resampling.LANCZOS)
    return _jpeg(region), round(scale, 2)

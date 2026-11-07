"""Raw pixels as a vector: the floor a glyph encoder has to clear (W0.3).

The programme's evaluation plan (§9.1) asks for a trivial baseline on raw
pixel statistics beside any vision model's number. Its purpose is to catch a
model that has learned the photograph (ink density, parchment tone, the scale
a page was shot at) rather than the letter. An encoder whose nearest
neighbours are no better than those of shrunken pixels has learned nothing
about letter shapes.

Each crop is turned to grey, padded to a square in its own edge colour (as the
encoder does, so the two see the same picture), shrunk to 16 × 16, centred on
its mean and scaled to unit length. It runs in this process, on Pillow alone:
there is no model, nothing leaves the server, and it costs nothing.
"""

import base64
import binascii
import io
import math

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest

SIDE = 16


def _edge_grey(image: Image.Image) -> int:
    width, height = image.size
    strips = [
        image.crop((0, 0, width, 1)),
        image.crop((0, height - 1, width, height)),
        image.crop((0, 0, 1, height)),
        image.crop((width - 1, 0, width, height)),
    ]
    total = sum(ImageStat.Stat(strip).sum[0] for strip in strips)
    count = sum(strip.size[0] * strip.size[1] for strip in strips)
    return int(round(total / count))


def pixel_vector(image: Image.Image) -> list[float]:
    """The crop as `SIDE * SIDE` mean-centred, unit-length grey values."""
    grey = image.convert("L")
    small = ImageOps.pad(grey, (SIDE, SIDE), method=Image.Resampling.BILINEAR, color=_edge_grey(grey))
    values = [float(value) for value in small.tobytes()]
    mean = sum(values) / len(values)
    centred = [value - mean for value in values]
    norm = math.sqrt(sum(value * value for value in centred))
    # A blank crop has no direction; its vector is zero and matches nothing.
    return [value / norm for value in centred] if norm else centred


class PixelProvider:
    """Shrunken pixels, for the baseline. Not a model."""

    model_name = "raw-pixels"
    model_version = f"{SIDE}x{SIDE}-grey-1"

    def run(self, request: InferenceRequest) -> InferenceResult:
        images = request.inputs.get("images")
        if not isinstance(images, list) or not images or not all(isinstance(image, str) for image in images):
            raise ProviderError("The pixel baseline takes a non-empty list of base64 images.")
        vectors = []
        for position, encoded in enumerate(images):
            try:
                image = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
                image.load()
            except (binascii.Error, UnidentifiedImageError, OSError) as exc:
                raise ProviderError(f"Image {position} is not a PNG or JPEG image ({exc}).") from None
            vectors.append(pixel_vector(image))
        return InferenceResult(
            output={"vectors": vectors, "dimensions": SIDE * SIDE},
            model_name=self.model_name,
            model_version=self.model_version,
            prompt_hash=content_digest(images),
        )

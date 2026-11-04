"""Classical shape descriptors for glyph crops (W1.2).

Networks trained on photographs, used as published, mostly find glyphs from the
same page: they recognise the photograph, not the letter. On this corpus, each
of these descriptors finds the same letter-form in another charter at least
four times as often as DINOv2-small does. Fused (`eval_glyph_encoder --fuse`),
they beat raw grey pixels, the §9.1 floor, by about ten points.

- `ink`: the crop binarised by Otsu's threshold, so parchment tone, ink
  density and lighting drop out. It is padded to a square, shrunk to
  32 × 32, mean-centred and scaled to unit length.
- `hog`: histograms of oriented gradients (Dalal and Triggs) on the
  contrast-stretched grey crop at 48 × 48. They use 6-pixel cells, 9 unsigned
  orientation bins, and 2 × 2-cell blocks normalised by L2-Hys. They record
  the direction of each stroke and tolerate small shifts.

Both pad in the crop's own edge colour, as the other encoders do, so a glyph
keeps its proportions. Both run in this process on Pillow and numpy: there is
no model, nothing leaves the server, and they cost nothing.
"""

import base64
import binascii
import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest

INK_SIDE = 32
HOG_SIDE, HOG_CELL, HOG_BINS = 48, 6, 9
# L2-Hys clips each normalised block at this value, then normalises again.
HOG_CLIP = 0.2


def _edge_fill(grey: np.ndarray) -> int:
    return int(round(np.concatenate([grey[0], grey[-1], grey[:, 0], grey[:, -1]]).mean()))


def _square(image: Image.Image, side: int) -> np.ndarray:
    """A grey crop padded to a square in its edge colour and resized, as floats."""
    fill = _edge_fill(np.asarray(image))
    padded = ImageOps.pad(image, (side, side), method=Image.Resampling.BICUBIC, color=fill)
    return np.asarray(padded, dtype=np.float64)


def _unit(vector: np.ndarray) -> list[float]:
    norm = float(np.linalg.norm(vector))
    # A blank crop has no direction; its vector is zero and matches nothing.
    return [float(value) for value in (vector / norm if norm else vector)]


def otsu_threshold(grey: np.ndarray) -> int:
    """The grey level that best separates ink from ground (Otsu, 1979)."""
    hist = np.bincount(grey.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    below = np.cumsum(hist)
    above = total - below
    level_sum = np.cumsum(hist * np.arange(256))
    mean_below = level_sum / np.where(below == 0, 1, below)
    mean_above = (level_sum[-1] - level_sum) / np.where(above == 0, 1, above)
    between = (below / total) * (above / total) * (mean_below - mean_above) ** 2
    return int(np.argmax(between))


def ink_vector(image: Image.Image) -> list[float]:
    """The crop's ink, black on white, as `INK_SIDE²` mean-centred unit values."""
    grey = np.asarray(image.convert("L"))
    ink = Image.fromarray(np.where(grey > otsu_threshold(grey), 255, 0).astype(np.uint8))
    values = _square(ink, INK_SIDE).ravel()
    return _unit(values - values.mean())


def hog(grey: np.ndarray, *, cell: int = HOG_CELL, bins: int = HOG_BINS) -> np.ndarray:
    """Histograms of oriented gradients over `grey`, block-normalised L2-Hys."""
    gx = np.zeros_like(grey)
    gy = np.zeros_like(grey)
    gx[:, 1:-1] = grey[:, 2:] - grey[:, :-2]
    gy[1:-1, :] = grey[2:, :] - grey[:-2, :]
    magnitude = np.hypot(gx, gy)
    # Unsigned orientation, each gradient shared between its two nearest bins.
    position = (np.rad2deg(np.arctan2(gy, gx)) % 180) / (180 / bins) - 0.5
    lower = np.floor(position).astype(int)
    share = position - lower

    cells_y, cells_x = grey.shape[0] // cell, grey.shape[1] // cell
    rows, cols = np.indices((cells_y * cell, cells_x * cell)) // cell
    magnitude = magnitude[: cells_y * cell, : cells_x * cell]
    lower = lower[: cells_y * cell, : cells_x * cell]
    share = share[: cells_y * cell, : cells_x * cell]
    histogram = np.zeros((cells_y, cells_x, bins))
    np.add.at(histogram, (rows, cols, lower % bins), magnitude * (1 - share))
    np.add.at(histogram, (rows, cols, (lower + 1) % bins), magnitude * share)

    blocks = []
    for y in range(cells_y - 1):
        for x in range(cells_x - 1):
            block = histogram[y : y + 2, x : x + 2].ravel()
            block = np.minimum(block / np.sqrt((block**2).sum() + 1e-6), HOG_CLIP)
            blocks.append(block / np.sqrt((block**2).sum() + 1e-6))
    return np.concatenate(blocks)


def hog_vector(image: Image.Image) -> list[float]:
    """The crop's stroke directions, as a unit vector."""
    grey = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    return _unit(hog(_square(grey, HOG_SIDE)))


HOG_DIMENSIONS = (HOG_SIDE // HOG_CELL - 1) ** 2 * 4 * HOG_BINS


class _ShapeProvider:
    """A descriptor run over each crop in the request. Not a model."""

    model_name: str
    model_version: str
    dimensions: int

    def describe(self, image: Image.Image) -> list[float]:
        raise NotImplementedError

    def run(self, request: InferenceRequest) -> InferenceResult:
        images = request.inputs.get("images")
        if not isinstance(images, list) or not images or not all(isinstance(image, str) for image in images):
            raise ProviderError(f"The {self.model_name} descriptor takes a non-empty list of base64 images.")
        vectors = []
        for position, encoded in enumerate(images):
            try:
                image = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
                image.load()
            except (binascii.Error, UnidentifiedImageError, OSError) as exc:
                raise ProviderError(f"Image {position} is not a PNG or JPEG image ({exc}).") from None
            vectors.append(self.describe(image))
        return InferenceResult(
            output={"vectors": vectors, "dimensions": self.dimensions},
            model_name=self.model_name,
            model_version=self.model_version,
            prompt_hash=content_digest(images),
        )


class InkProvider(_ShapeProvider):
    model_name = "ink"
    model_version = f"otsu-{INK_SIDE}-1"
    dimensions = INK_SIDE * INK_SIDE

    def describe(self, image: Image.Image) -> list[float]:
        return ink_vector(image)


class HogProvider(_ShapeProvider):
    model_name = "hog"
    model_version = f"{HOG_SIDE}px-{HOG_CELL}cell-{HOG_BINS}bin-1"
    dimensions = HOG_DIMENSIONS

    def describe(self, image: Image.Image) -> list[float]:
        return hog_vector(image)

"""Finding a letter's other examples on a page from the ones marked there (W3.4).

The page is described as dense histograms of oriented gradients, with the
`hog` encoder's 6-pixel cells, 9 unsigned bins and L2-Hys 2 × 2-cell blocks,
rendered so that the examples' usual side spans one 48-pixel window. Every
window on the page is scored by its cosine to the mean of the examples'
windows, once the page's mean block has been taken from every block. Without
that step any patch of writing scores about 0.8 against any other, because the
histograms are all positive. The best windows, kept apart by non-maximum
suppression and clear of what is already marked, are the proposals.

It runs in this process on numpy alone: no model, nothing leaves the server,
and it costs nothing. What it finds is a candidate for a human to confirm, never
an annotation.
"""

import base64
import binascii
import io
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest
from .shape import HOG_BINS, HOG_CELL, HOG_CLIP, HOG_SIDE

# Blocks along a window's side: a 48-pixel window has 8 cells, so 7 blocks.
WINDOW_BLOCKS = HOG_SIDE // HOG_CELL - 1
# Two proposals are kept at least this many cells apart, about half a letter.
SUPPRESS_CELLS = WINDOW_BLOCKS // 2 + 1
# A window whose centre falls in a marked box, grown by this share of the box,
# is something already annotated.
MARKED_SLACK = 0.15
# The longest side of page this will search, in pixels of the rendition.
MAX_SIDE = 6000
MAX_COUNT = 200


def page_blocks(grey: np.ndarray) -> np.ndarray:
    """The page's L2-Hys blocks, `(rows, cols, 36)`, each less the page's mean block.

    Each block is the one `shape.hog` computes for the same 2 × 2 cells, so a
    window of 7 × 7 blocks describes its 48 pixels as the encoder would.
    """
    gx = np.zeros_like(grey)
    gy = np.zeros_like(grey)
    gx[:, 1:-1] = grey[:, 2:] - grey[:, :-2]
    gy[1:-1, :] = grey[2:, :] - grey[:-2, :]
    magnitude = np.hypot(gx, gy)
    position = (np.rad2deg(np.arctan2(gy, gx)) % 180) / (180 / HOG_BINS) - 0.5
    lower = np.floor(position).astype(int)
    share = position - lower
    cells_y, cells_x = grey.shape[0] // HOG_CELL, grey.shape[1] // HOG_CELL
    if cells_y < WINDOW_BLOCKS + 1 or cells_x < WINDOW_BLOCKS + 1:
        raise ProviderError("The page is smaller than one window.")
    span = (slice(0, cells_y * HOG_CELL), slice(0, cells_x * HOG_CELL))
    rows, cols = np.indices((cells_y * HOG_CELL, cells_x * HOG_CELL)) // HOG_CELL
    histogram = np.zeros((cells_y, cells_x, HOG_BINS))
    np.add.at(histogram, (rows, cols, lower[span] % HOG_BINS), magnitude[span] * (1 - share[span]))
    np.add.at(histogram, (rows, cols, (lower[span] + 1) % HOG_BINS), magnitude[span] * share[span])
    # Cells in the order `shape.hog` ravels a 2 × 2 block: top left, top right, bottom left, bottom right.
    blocks = np.concatenate([histogram[:-1, :-1], histogram[:-1, 1:], histogram[1:, :-1], histogram[1:, 1:]], axis=2)
    blocks = blocks / np.sqrt((blocks**2).sum(-1, keepdims=True) + 1e-6)
    blocks = np.minimum(blocks, HOG_CLIP)
    blocks = blocks / np.sqrt((blocks**2).sum(-1, keepdims=True) + 1e-6)
    return blocks - blocks.reshape(-1, blocks.shape[-1]).mean(0)


def _window_origin(cx: float, cy: float) -> tuple[int, int]:
    """The block at the top left of the window centred on pixel (cx, cy)."""
    return int(round((cy - HOG_SIDE / 2) / HOG_CELL)), int(round((cx - HOG_SIDE / 2) / HOG_CELL))


def _window_centre(row: int, col: int) -> tuple[float, float]:
    return col * HOG_CELL + HOG_SIDE / 2, row * HOG_CELL + HOG_SIDE / 2


def window(blocks: np.ndarray, cx: float, cy: float) -> np.ndarray | None:
    """The window centred on pixel (cx, cy), or None when it runs off the page."""
    row, col = _window_origin(cx, cy)
    if row < 0 or col < 0 or row + WINDOW_BLOCKS > blocks.shape[0] or col + WINDOW_BLOCKS > blocks.shape[1]:
        return None
    return blocks[row : row + WINDOW_BLOCKS, col : col + WINDOW_BLOCKS]


def scores(blocks: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Every window's cosine to `template`, indexed by the window's top-left block."""
    rows = blocks.shape[0] - WINDOW_BLOCKS + 1
    cols = blocks.shape[1] - WINDOW_BLOCKS + 1
    dot = np.zeros((rows, cols))
    squared = np.zeros((rows, cols))
    lengths = (blocks**2).sum(-1)
    for i in range(WINDOW_BLOCKS):
        for j in range(WINDOW_BLOCKS):
            dot += blocks[i : i + rows, j : j + cols] @ template[i, j]
            squared += lengths[i : i + rows, j : j + cols]
    return dot / (np.sqrt(squared) * np.linalg.norm(template) + 1e-9)


def _inside(cx: float, cy: float, box: list[float], slack: float = MARKED_SLACK) -> bool:
    x, y, w, h = box
    return x - slack * w <= cx <= x + w * (1 + slack) and y - slack * h <= cy <= y + h * (1 + slack)


def find(grey: np.ndarray, examples: list[list[float]], marked: list[list[float]], count: int) -> list[dict]:
    """The `count` windows most like the examples, best first, none on an example or a marked box.

    Boxes are `[x, y, w, h]` in the page's pixels, origin at the top left. A
    proposal is as wide and tall as the examples' median and centred on its
    window.
    """
    blocks = page_blocks(grey)
    found = [window(blocks, x + w / 2, y + h / 2) for x, y, w, h in examples]
    descriptors = [part / np.linalg.norm(part) for part in found if part is not None]
    if not descriptors:
        raise ProviderError("No example lies wholly on the page.")
    grid = scores(blocks, np.mean(descriptors, axis=0))
    width = float(np.median([w for _, _, w, _ in examples]))
    height = float(np.median([h for _, _, _, h in examples]))

    blocked = [*examples, *marked]
    taken = np.zeros(grid.shape, dtype=bool)
    proposals: list[dict] = []
    for flat in np.argsort(grid, axis=None)[::-1]:
        row, col = divmod(int(flat), grid.shape[1])
        if taken[row, col]:
            continue
        # A marked letter still keeps its neighbourhood clear, or its edges would be proposed.
        taken[
            max(0, row - SUPPRESS_CELLS) : row + SUPPRESS_CELLS + 1,
            max(0, col - SUPPRESS_CELLS) : col + SUPPRESS_CELLS + 1,
        ] = True
        cx, cy = _window_centre(row, col)
        if any(_inside(cx, cy, box) for box in blocked):
            continue
        proposals.append(
            {
                "x": cx - width / 2,
                "y": cy - height / 2,
                "w": width,
                "h": height,
                "score": round(float(grid[row, col]), 4),
            }
        )
        if len(proposals) >= count:
            break
    return proposals


def page_grey(image: Image.Image) -> np.ndarray:
    """The page in grey, as floats. Each block is normalised, so its contrast does not matter."""
    return np.asarray(image.convert("L"), dtype=np.float64)


def _boxes(value: Any, name: str) -> list[list[float]]:
    if not isinstance(value, list) or not all(
        isinstance(box, list) and len(box) == 4 and all(isinstance(v, int | float) for v in box) for box in value
    ):
        raise ProviderError(f"`{name}` must be a list of [x, y, w, h] boxes.")
    return [[float(v) for v in box] for box in value]


class PageSearchProvider:
    """The examples' other likenesses on one page. Not a model."""

    model_name = "hog-page"
    model_version = f"{HOG_SIDE}px-{HOG_CELL}cell-{HOG_BINS}bin-centred-1"

    def run(self, request: InferenceRequest) -> InferenceResult:
        inputs = request.inputs
        page, count = inputs.get("page"), inputs.get("count")
        if not isinstance(page, str):
            raise ProviderError("`page` must be a base64 image.")
        examples = _boxes(inputs.get("examples"), "examples")
        marked = _boxes(inputs.get("marked", []), "marked")
        if not examples:
            raise ProviderError("There are no examples to search by.")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= MAX_COUNT:
            raise ProviderError(f"`count` must be a whole number from 1 to {MAX_COUNT}.")
        try:
            image = Image.open(io.BytesIO(base64.b64decode(page, validate=True)))
            image.load()
        except (binascii.Error, UnidentifiedImageError, OSError) as exc:
            raise ProviderError(f"The page is not a PNG or JPEG image ({exc}).") from None
        if max(image.size) > MAX_SIDE:
            raise ProviderError(f"The page is {image.size[0]} × {image.size[1]}; the most this searches is {MAX_SIDE}.")
        return InferenceResult(
            output={"boxes": find(page_grey(image), examples, marked, count)},
            model_name=self.model_name,
            model_version=self.model_version,
            prompt_hash=content_digest({"page": page, "examples": examples, "marked": marked, "count": count}),
        )

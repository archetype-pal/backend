"""Finding a page's letters, each with its box and its allograph (AI programme W1.1).

Kraken has already read the page: every character CATMuS reads has a place on
its line, where the recogniser emitted it, and the line runs from a top to a
bottom there. That place is a point, not a span, so Kraken alone cannot draw a
letter's box. Two small networks, trained on this corpus's expert boxes by
`train_letters.py`, do the rest:

- **The box model** looks at a window around the point, four line-heights
  square, with the character read there and how far off its neighbours are,
  and draws the box an expert would draw. It also says how well it expects its
  box to fit: its estimate of the overlap (IoU) with an expert's.
- **The classifier** looks at that box, as a reviewer sees it, with the
  character read there, and names the allograph, with its probability.

CATMuS cannot tell allographs apart itself: it writes long and round s alike,
and one r for both forms. The classifier exists for that.

Both are ResNet-18s, small enough to run on the CPU this service already uses.
Their weights are not in the image: they are trained on the corpus and kept
beside it, in `HTR_LETTERS_DIR`, as `letters.pt` with a manifest,
`letters.json`, that names the weights' SHA-256, the release they were trained
on and the numbers they scored on its held-out charters. The service checks the
digest before it loads them, and every answer names it, so a proposal can always
be traced to the weights that made it. Without them the service still reads.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Self
import unicodedata

import numpy as np
from PIL import Image
import torch
from torch import nn
import torchvision

# Kraken reads the page with its longer side at most this many pixels: the segmenter
# scales every page to one height anyway, and this bounds the recogniser's memory.
# The models then look at the page as it was sent.
READ_SIDE = 2900
# The box model's window: SIDE pixels, WINDOW line-heights square, centred on the character.
SIDE = 160
WINDOW = 4.0
# The classifier's crop: the box, squared and grown by MARGIN on each side, at CLASS_SIDE pixels.
CLASS_SIDE = 128
MARGIN = 0.15
# A line shorter than this, in pixels, is taken to be this tall.
MIN_LINE = 8.0
# Neighbours further off than this, in line-heights, count as this far.
MAX_GAP = 3.0
BATCH = 128
# ImageNet's normalisation, which the backbones were pretrained with.
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


@dataclass(frozen=True)
class Anchor:
    """A character as Kraken read it: where it is on the page, in the page's pixels."""

    char: str
    confidence: float
    x: float
    y: float
    line_height: float
    gaps: tuple[float, float, float, float]
    line: int

    @property
    def base(self) -> str:
        """The character without its combining marks: what the models are told was read."""
        stripped = "".join(c for c in unicodedata.normalize("NFD", self.char) if not unicodedata.combining(c))
        return stripped or self.char


def for_reading(page: Image.Image) -> tuple[Image.Image, float]:
    """The page as Kraken reads it, and the scale from it back to the page."""
    scale = min(1.0, READ_SIDE / max(page.size))
    if scale == 1.0:
        return page, 1.0
    size = (max(1, round(page.width * scale)), max(1, round(page.height * scale)))
    return page.resize(size, Image.Resampling.LANCZOS), 1 / scale


def reading(records: Any, *, scale: float = 1.0) -> list[dict[str, Any]]:
    """Kraken's records as lines of characters: each its place on the line and the line's extent there.

    `scale` takes the positions from the image Kraken read to the page's pixels.
    """
    lines = []
    for record in records:
        characters = []
        for char, cut, confidence in zip(record.prediction, record.cuts, record.confidences, strict=True):
            xs = [point[0] * scale for point in cut]
            ys = [point[1] * scale for point in cut]
            characters.append(
                {
                    "char": char,
                    "confidence": float(confidence),
                    "x": (min(xs) + max(xs)) / 2,
                    "top": min(ys),
                    "bottom": max(ys),
                }
            )
        lines.append({"text": record.prediction, "characters": characters})
    return lines


def anchors(lines: list[dict[str, Any]]) -> list[Anchor]:
    """Every character but spaces, with how far off its neighbours are in line-heights."""
    found = []
    for number, line in enumerate(lines):
        characters = line["characters"]
        for i, c in enumerate(characters):
            if c["char"].isspace():
                continue
            height = max(MIN_LINE, c["bottom"] - c["top"])
            before = characters[i - 1] if i > 0 else None
            after = characters[i + 1] if i + 1 < len(characters) else None
            gaps = (
                min(MAX_GAP, (c["x"] - before["x"]) / height) if before else 1.0,
                min(MAX_GAP, (after["x"] - c["x"]) / height) if after else 1.0,
                float(bool(before and before["char"].isspace())),
                float(bool(after and after["char"].isspace())),
            )
            found.append(
                Anchor(
                    char=c["char"],
                    confidence=c["confidence"],
                    x=c["x"],
                    y=(c["top"] + c["bottom"]) / 2,
                    line_height=height,
                    gaps=gaps,
                    line=number,
                )
            )
    return found


def window(grey: Image.Image, anchor: Anchor, *, side: int = SIDE, span: float = WINDOW) -> np.ndarray:
    """The box model's view of a character: `span` line-heights square around it, at `side` pixels."""
    half = span * anchor.line_height / 2
    extent = (anchor.x - half, anchor.y - half, anchor.x + half, anchor.y + half)
    view = grey.transform((side, side), Image.Transform.EXTENT, extent, Image.Resampling.BILINEAR, fillcolor=255)
    return np.asarray(view, dtype=np.uint8)


def box_from_window(fractions: list[float], anchor: Anchor, *, span: float = WINDOW) -> list[float]:
    """A box the box model drew, as fractions of its window, in page pixels: [x, y, width, height]."""
    side = span * anchor.line_height
    left, top = anchor.x - side / 2, anchor.y - side / 2
    x0, y0, x1, y1 = fractions
    return [left + x0 * side, top + y0 * side, (x1 - x0) * side, (y1 - y0) * side]


def box_to_window(box: list[float], anchor: Anchor, *, span: float = WINDOW) -> list[float]:
    """A page box as fractions of the character's window: [x0, y0, x1, y1]."""
    side = span * anchor.line_height
    x0 = (box[0] - (anchor.x - side / 2)) / side
    y0 = (box[1] - (anchor.y - side / 2)) / side
    return [x0, y0, x0 + box[2] / side, y0 + box[3] / side]


def box_view(grey: Image.Image, box: list[float]) -> np.ndarray:
    """The classifier's view of a box: squared, grown by MARGIN, at CLASS_SIDE pixels."""
    x, y, width, height = box
    side = max(width, height) * (1 + 2 * MARGIN)
    cx, cy = x + width / 2, y + height / 2
    extent = (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
    view = grey.transform(
        (CLASS_SIDE, CLASS_SIDE), Image.Transform.EXTENT, extent, Image.Resampling.BILINEAR, fillcolor=255
    )
    return np.asarray(view, dtype=np.uint8)


def to_tensor(views: list[np.ndarray]) -> torch.Tensor:
    """Greyscale views as a normalised three-channel batch."""
    x = torch.from_numpy(np.stack(views).astype(np.float32) / 255.0).unsqueeze(1).repeat(1, 3, 1, 1)
    return (x - MEAN) / STD


def backbone(*, pretrained: bool) -> nn.Module:
    weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
    net = torchvision.models.resnet18(weights=weights)
    net.fc = nn.Identity()
    return net


FEATURES = 512


class BoxModel(nn.Module):
    """A character's window → the expert's box, as fractions of the window, and how well it should fit."""

    def __init__(self, characters: int, *, pretrained: bool = False) -> None:
        super().__init__()
        self.backbone = backbone(pretrained=pretrained)
        self.char = nn.Embedding(characters, 32)
        width = FEATURES + 32 + 4
        self.head = nn.Sequential(nn.Linear(width, 256), nn.ReLU(), nn.Dropout(0.1), nn.Linear(256, 4))
        self.quality = nn.Sequential(nn.Linear(width, 128), nn.ReLU(), nn.Linear(128, 1))

    def forward(
        self, views: torch.Tensor, chars: torch.Tensor, gaps: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        features = torch.cat([self.backbone(views), self.char(chars), gaps], dim=1)
        out = self.head(features)
        # A box centred somewhere in the window, its size positive.
        cx = 0.5 + 0.5 * torch.tanh(out[:, 0])
        cy = 0.5 + 0.5 * torch.tanh(out[:, 1])
        width = torch.exp(out[:, 2].clamp(-6, 2)) * 0.2
        height = torch.exp(out[:, 3].clamp(-6, 2)) * 0.3
        box = torch.stack([cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2], dim=1)
        return box, torch.sigmoid(self.quality(features)).squeeze(1)


class Classifier(nn.Module):
    """A box's view, the character read there and the box's shape → a score for each allograph."""

    def __init__(self, characters: int, allographs: int, *, pretrained: bool = False) -> None:
        super().__init__()
        self.backbone = backbone(pretrained=pretrained)
        self.char = nn.Embedding(characters, 32)
        self.head = nn.Sequential(
            nn.Linear(FEATURES + 32 + 1, 256), nn.ReLU(), nn.Dropout(0.3), nn.Linear(256, allographs)
        )

    def forward(self, views: torch.Tensor, chars: torch.Tensor, aspect: torch.Tensor) -> torch.Tensor:
        return self.head(torch.cat([self.backbone(views), self.char(chars), aspect], dim=1))


class LetterModels:
    """The box model and the classifier, loaded once from `letters.pt` once its digest is checked."""

    def __init__(self, checkpoint: dict[str, Any], *, manifest: dict[str, Any], revision: str) -> None:
        self.characters: dict[str, int] = checkpoint["characters"]
        self.allographs: list[tuple[str, str]] = [tuple(pair) for pair in checkpoint["allographs"]]
        self.box_model = BoxModel(len(self.characters))
        self.box_model.load_state_dict(checkpoint["box_model"])
        self.box_model.eval()
        self.classifier = Classifier(len(self.characters), len(self.allographs))
        self.classifier.load_state_dict(checkpoint["classifier"])
        self.classifier.eval()
        self.manifest = manifest
        self.revision = revision

    @classmethod
    def load(cls, directory: Path) -> Self:
        manifest_path, weights_path = directory / "letters.json", directory / "letters.pt"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(weights_path.read_bytes()).hexdigest()
        if digest != manifest.get("sha256"):
            raise RuntimeError(f"{weights_path} has SHA-256 {digest}, but its manifest names {manifest.get('sha256')}.")
        checkpoint = torch.load(weights_path, map_location="cpu", weights_only=True)
        return cls(checkpoint, manifest=manifest, revision=digest)

    def describe(self) -> dict[str, Any]:
        return {
            "name": str(self.manifest.get("name", "letters")),
            "revision": self.revision,
            "release": self.manifest.get("release"),
        }

    def character(self, anchor: Anchor) -> int:
        return self.characters.get(anchor.base, 0)

    @torch.no_grad()
    def find(self, grey: Image.Image, found: list[Anchor]) -> list[dict[str, Any]]:
        """Each character's box, its expected fit, and its likeliest allograph with that allograph's probability."""
        letters: list[dict[str, Any]] = []
        for start in range(0, len(found), BATCH):
            batch = found[start : start + BATCH]
            chars = torch.tensor([self.character(a) for a in batch])
            gaps = torch.tensor([a.gaps for a in batch], dtype=torch.float32)
            fractions, quality = self.box_model(to_tensor([window(grey, a) for a in batch]), chars, gaps)
            boxes = [box_from_window(f, a) for f, a in zip(fractions.tolist(), batch, strict=True)]
            aspect = torch.tensor([[b[2] / max(b[3], 1.0)] for b in boxes], dtype=torch.float32)
            scores = self.classifier(to_tensor([box_view(grey, b) for b in boxes]), chars, aspect).softmax(1)
            probability, index = scores.max(1)
            for anchor, box, fit, p, k in zip(
                batch, boxes, quality.tolist(), probability.tolist(), index.tolist(), strict=True
            ):
                character, allograph = self.allographs[k]
                letters.append(
                    {
                        "read": anchor.char,
                        "read_confidence": round(anchor.confidence, 4),
                        "line": anchor.line,
                        "box": [round(v, 1) for v in box],
                        "fit": round(fit, 4),
                        "character": character,
                        "allograph": allograph,
                        "probability": round(p, 4),
                    }
                )
        return letters

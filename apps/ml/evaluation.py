"""Scoring held-out predictions (AI programme W0.3).

Evaluation runs against a **frozen release on disk**, never the live database.
That is the whole reason W0.2 writes its splits into the release: a number
computed against a moving corpus cannot be reproduced, and a benchmark nobody
can reproduce is a claim rather than a measurement.

The harness computes no numbers it will not also compute for a baseline. "No
model ships without numbers, and no number ships without its split and its
baseline" is enforced in `apps.ml.services.evaluation`, not left to discipline.
"""

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import random
from typing import Any


class ReleaseError(Exception):
    """A dataset release is missing or malformed."""


@dataclass(frozen=True)
class Metrics:
    """Scores for one prediction set. Per-class support travels with the score.

    Per-class numbers are meaningless without their support — 18 of the corpus's
    97 attested classes have fewer than 20 examples — so the two are one object
    and cannot be reported apart.
    """

    n: int
    accuracy: float
    macro_f1: float
    per_class: dict[str, dict[str, float]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1, 4),
            "per_class": self.per_class,
        }


def score(y_true: list[str], y_pred: list[str]) -> Metrics:
    """Accuracy, macro-F1 and per-class precision/recall/F1/support."""
    if len(y_true) != len(y_pred):
        raise ValueError(f"Mismatched lengths: {len(y_true)} truths, {len(y_pred)} predictions.")
    if not y_true:
        raise ValueError("Nothing to score.")

    labels = sorted(set(y_true) | set(y_pred))
    per_class: dict[str, dict[str, float]] = {}
    f1s = []
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        # Macro-F1 averages over classes that are actually present in the truth;
        # a class the model hallucinated should not dilute the average with a
        # free zero, and a class absent from the held-out set has no F1 to give.
        if support:
            f1s.append(f1)
        per_class[label] = {
            "support": support,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    correct = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p)
    return Metrics(
        n=len(y_true),
        accuracy=correct / len(y_true),
        macro_f1=sum(f1s) / len(f1s) if f1s else 0.0,
        per_class=per_class,
    )


def majority_baseline(train_labels: list[str], n: int) -> list[str]:
    """Always predict the commonest training class.

    The floor any headline accuracy must clear. On a skewed taxonomy it is
    higher than intuition suggests, which is exactly why it has to be published
    beside the model's number rather than assumed to be near zero.
    """
    if not train_labels:
        raise ValueError("No training labels to derive a majority class from.")
    commonest = Counter(train_labels).most_common(1)[0][0]
    return [commonest] * n


def stratified_baseline(train_labels: list[str], n: int, *, seed: str) -> list[str]:
    """Sample predictions from the training class prior.

    Seeded from the release version so the baseline is reproducible: a floor
    that moves between runs is not a floor.
    """
    if not train_labels:
        raise ValueError("No training labels to derive a prior from.")
    rng = random.Random(seed)
    return rng.choices(train_labels, k=n)


# §9.1 also asks for a trivial baseline on raw pixel statistics, to expose a
# model that has learned to recognise the photograph rather than the script.
# It needs pixels, which the pixel-free release deliberately does not carry, so
# it becomes available only with the crop release — after W0.4's clearance.
PIXEL_BASELINE_UNAVAILABLE = (
    "A raw-pixel nearest-neighbour baseline needs image data. The pixel-free "
    "release carries none, so this baseline is unavailable until the crop "
    "release clears W0.4."
)


@dataclass(frozen=True)
class Release:
    """A frozen dataset release, loaded from disk."""

    path: Path
    manifest: dict[str, Any]
    splits: dict[str, Any]
    glyphs: list[dict[str, Any]]

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", ""))

    def partition(self, split: str = "by_charter") -> tuple[list[dict], list[dict]]:
        """(train, held_out) glyph rows for the named split.

        Grouped: membership is decided by the row's charter or repository, never
        by the row itself, so no glyph from a held-out charter leaks into train.
        """
        try:
            groups = self.splits[split]
        except KeyError:
            raise ReleaseError(f"Release {self.version} has no split '{split}'.") from None

        key = "item_part_id" if split == "by_charter" else "repository"
        held = set(groups.get("held_out", []))
        train = [row for row in self.glyphs if row.get(key) not in held]
        held_out = [row for row in self.glyphs if row.get(key) in held]
        return train, held_out


def load_release(path: str | Path) -> Release:
    """Load a release directory written by `export_glyph_dataset`."""
    root = Path(path)
    required = ("manifest.json", "splits.json", "glyphs.jsonl")
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ReleaseError(f"{root} is not a release: missing {', '.join(missing)}.")

    with (root / "manifest.json").open(encoding="utf-8") as fh:
        manifest = json.load(fh)
    with (root / "splits.json").open(encoding="utf-8") as fh:
        splits = json.load(fh)
    with (root / "glyphs.jsonl").open(encoding="utf-8") as fh:
        glyphs = [json.loads(line) for line in fh if line.strip()]

    return Release(path=root, manifest=manifest, splits=splits, glyphs=glyphs)

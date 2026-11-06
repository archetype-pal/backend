"""Train the letter models (W1.1) on a glyph release, and score them on its held-out charters.

    python train_letters.py --release <release dir> --pages <pages dir> --out <dir> [--device mps]

`--release` is a directory `export_glyph_dataset` wrote: every expert box, as a
IIIF region of its page, with its allograph, and the split by charter. `--pages`
is what `export_letter_pages` wrote beside it: the release's pages as JPEGs,
their longer side at most the size the backend sends this service, and
`pages.json` saying which is which.

Each page is read with the same Kraken pass `/letters` uses, and each expert box
is matched to the character read inside it. The box model learns, from the
character's window, the box the expert drew; the classifier learns, from that
box, the allograph the expert named. Charters the release holds out are never
trained on: they are where the numbers come from, beside two baselines
measured on the same boxes. The box baseline gives each character the median
size and offset of its expert boxes, in line-heights; the allograph baseline
names the allograph experts most often gave the character read.

Writes `letters.pt` and `letters.json` (its SHA-256, the release, the split and
the numbers) into `--out`. Kraken's readings are kept in `--pages` as
`<id>.reading.json`, so a second run does not read the pages again.

It needs the ImageNet weights torchvision fetches for a ResNet-18 the first time
it runs; the service itself needs nothing beyond `letters.pt`. On a CPU a full
release takes hours; `--device mps` or `cuda` takes minutes.
"""

import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import statistics
import time
from typing import Any

from kraken import blla, rpred
from kraken.lib import models as kraken_models
import letters
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F

logger = logging.getLogger("train_letters")

Image.MAX_IMAGE_PIXELS = None
# Stored windows are larger than the model's, so each epoch can shift them a little.
OUTER = 1.125
STORED = round(letters.SIDE * OUTER)
# The share of the training charters kept back to watch training by.
VALIDATION_FOLDS = 10
# Each expert box is shown to the classifier this many times, all but the first jittered.
CLASSIFIER_COPIES = 4
# What an expert names a letter, as CATMuS writes it, when the two differ.
WRITTEN_AS = {"7": "⁊", "-us": "ꝰ", "-rum": "ꝵ", "con": "ꝯ", "per": "ꝑ", "pro": "ꝓ", "et (&)": "&"}
THRESHOLDS = (0.5, 0.7, 0.9)
FIT_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)


# ---------------------------------------------------------------- data


def region(text: str, scale: float) -> list[float]:
    x, y, width, height = (float(v) for v in text.split(","))
    return [x * scale, y * scale, width * scale, height * scale]


def held_out_charters(release: Path) -> set[int]:
    splits = json.loads((release / "splits.json").read_text(encoding="utf-8"))
    return set(splits["by_charter"]["held_out"])


def watched(item_part_id: int) -> bool:
    """A training charter kept back to watch training by: a fixed tenth, by digest."""
    digest = hashlib.sha256(f"letters:{item_part_id}".encode()).hexdigest()
    return int(digest, 16) % VALIDATION_FOLDS == 0


def read_pages(pages_dir: Path, kraken_path: str, device: str) -> dict[int, list[dict[str, Any]]]:
    """Kraken's reading of every page, from the cache or read now."""
    index = json.loads((pages_dir / "pages.json").read_text(encoding="utf-8"))
    kraken_digest = hashlib.sha256(Path(kraken_path).read_bytes()).hexdigest()
    model = None
    readings = {}
    started = time.monotonic()
    for number, page in enumerate(index, start=1):
        cache = pages_dir / f"{page['item_image_id']}.reading.json"
        if cache.is_file():
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("kraken") == kraken_digest and cached.get("read_side") == letters.READ_SIDE:
                readings[page["item_image_id"]] = cached["lines"]
                continue
        if model is None:
            model = kraken_models.load_any(kraken_path, device=device)
        image = Image.open(pages_dir / page["file"]).convert("RGB")
        view, scale = letters.for_reading(image)
        records = list(rpred.rpred(model, view, blla.segment(view, device=device)))
        lines = letters.reading(records, scale=scale)
        cache.write_text(
            json.dumps({"kraken": kraken_digest, "read_side": letters.READ_SIDE, "lines": lines}, ensure_ascii=False),
            encoding="utf-8",
        )
        readings[page["item_image_id"]] = lines
        elapsed = time.monotonic() - started
        logger.info("Read page %s (%d/%d), %.0fs.", page["item_image_id"], number, len(index), elapsed)
    return readings


def match(boxes: list[dict[str, Any]], found: list[letters.Anchor]) -> dict[int, int]:
    """Expert box → the character read inside it: the one the expert named if read, else the most central."""
    pairs = {}
    for i, glyph in enumerate(boxes):
        x, y, width, height = glyph["box"]
        cx, cy = x + width / 2, y + height / 2
        named = WRITTEN_AS.get(glyph["character"], glyph["character"][:1]).lower()
        best, best_key = None, None
        for j, anchor in enumerate(found):
            if not (x <= anchor.x <= x + width and y - 0.25 * height <= anchor.y <= y + 1.25 * height):
                continue
            key = (anchor.base[:1].lower() != named, abs(anchor.x - cx) / width + abs(anchor.y - cy) / height)
            if best_key is None or key < best_key:
                best, best_key = j, key
        if best is not None:
            pairs[i] = best
    return pairs


def load(args: argparse.Namespace) -> list[dict[str, Any]]:
    """The release's pages that have a picture, each with its expert boxes, its reading and its part of the split."""
    release, pages_dir = Path(args.release), Path(args.pages)
    held = held_out_charters(release)
    glyphs = defaultdict(list)
    with (release / "glyphs.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("iiif_region"):
                glyphs[row["item_image_id"]].append(row)
    readings = read_pages(pages_dir, args.kraken_model, args.device)
    pages = []
    for page in json.loads((pages_dir / "pages.json").read_text(encoding="utf-8")):
        rows = glyphs.get(page["item_image_id"])
        if not rows:
            continue
        scale = page["scale"]
        boxes = [
            {"box": region(r["iiif_region"], scale), "character": r["character"], "allograph": r["allograph"]}
            for r in rows
        ]
        found = letters.anchors(readings[page["item_image_id"]])
        part = page["item_part_id"]
        split = "test" if part in held else "validation" if watched(part) else "train"
        pages.append({**page, "split": split, "boxes": boxes, "anchors": found, "pairs": match(boxes, found)})
    return pages


# ---------------------------------------------------------------- the box model


def box_samples(pages: list[dict[str, Any]], split: str, characters: dict[str, int], pages_dir: Path) -> list[dict]:
    samples = []
    for page in pages:
        if page["split"] != split:
            continue
        grey = Image.open(pages_dir / page["file"]).convert("L")
        for i, j in page["pairs"].items():
            anchor = page["anchors"][j]
            samples.append(
                {
                    "view": letters.window(grey, anchor, side=STORED, span=letters.WINDOW * OUTER),
                    "target": letters.box_to_window(page["boxes"][i]["box"], anchor),
                    "char": characters.get(anchor.base, 0),
                    "gaps": anchor.gaps,
                }
            )
    return samples


def box_batch(samples: list[dict], *, train: bool, device: str) -> tuple[torch.Tensor, ...]:
    views, targets = [], []
    for sample in samples:
        if train:
            dx, dy = random.randint(0, STORED - letters.SIDE), random.randint(0, STORED - letters.SIDE)
        else:
            dx = dy = (STORED - letters.SIDE) // 2
        view = sample["view"][dy : dy + letters.SIDE, dx : dx + letters.SIDE]
        if train:
            view = jitter_light(view)
        views.append(view)
        # The target, from the stored window to this one.
        shift = (STORED - letters.SIDE) / 2
        sx, sy = (dx - shift) / letters.SIDE, (dy - shift) / letters.SIDE
        x0, y0, x1, y1 = sample["target"]
        targets.append([x0 - sx, y0 - sy, x1 - sx, y1 - sy])
    chars = [0 if train and random.random() < 0.05 else s["char"] for s in samples]
    return (
        letters.to_tensor(views).to(device),
        torch.tensor(chars).to(device),
        torch.tensor([s["gaps"] for s in samples], dtype=torch.float32).to(device),
        torch.tensor(targets, dtype=torch.float32).to(device),
    )


def jitter_light(view: np.ndarray) -> np.ndarray:
    """Contrast and brightness shifted a little, as photographs of parchment differ."""
    scaled = (view.astype(np.float32) - 127.5) * random.uniform(0.7, 1.3) + 127.5 + random.uniform(-25, 25)
    return np.clip(scaled, 0, 255).astype(np.uint8)


def overlap(predicted: torch.Tensor, target: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """(generalised-IoU loss, IoU) of corner boxes."""
    ix0, iy0 = torch.max(predicted[:, 0], target[:, 0]), torch.max(predicted[:, 1], target[:, 1])
    ix1, iy1 = torch.min(predicted[:, 2], target[:, 2]), torch.min(predicted[:, 3], target[:, 3])
    inter = (ix1 - ix0).clamp(min=0) * (iy1 - iy0).clamp(min=0)
    area_p = (predicted[:, 2] - predicted[:, 0]) * (predicted[:, 3] - predicted[:, 1])
    area_t = (target[:, 2] - target[:, 0]) * (target[:, 3] - target[:, 1])
    union = area_p + area_t - inter
    iou = inter / union.clamp(min=1e-6)
    hx0, hy0 = torch.min(predicted[:, 0], target[:, 0]), torch.min(predicted[:, 1], target[:, 1])
    hx1, hy1 = torch.max(predicted[:, 2], target[:, 2]), torch.max(predicted[:, 3], target[:, 3])
    hull = ((hx1 - hx0) * (hy1 - hy0)).clamp(min=1e-6)
    return (1 - iou + (hull - union) / hull).mean(), iou


def schedule(model: torch.nn.Module, steps: int) -> tuple[torch.optim.Optimizer, Any]:
    optimiser = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    return optimiser, torch.optim.lr_scheduler.OneCycleLR(optimiser, max_lr=1e-3, total_steps=steps, pct_start=0.1)


def train_box_model(train: list[dict], validation: list[dict], characters: int, args) -> letters.BoxModel:
    model = letters.BoxModel(characters, pretrained=True).to(args.device)
    optimiser, scheduler = schedule(model, args.box_epochs * -(-len(train) // args.batch))
    started = time.monotonic()
    for epoch in range(1, args.box_epochs + 1):
        model.train()
        random.shuffle(train)
        for start in range(0, len(train), args.batch):
            views, chars, gaps, target = box_batch(train[start : start + args.batch], train=True, device=args.device)
            box, fit = model(views, chars, gaps)
            giou, iou = overlap(box, target)
            loss = giou + 5 * F.l1_loss(box, target) + F.binary_cross_entropy(fit, iou.detach().clamp(0, 1))
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            scheduler.step()
        if epoch % 5 == 0 or epoch == args.box_epochs:
            ious = box_ious(model, validation, args.device)
            logger.info(
                "Box model, epoch %d: on watched charters, IoU >= 0.5 for %.1f%%, median %.2f (%.0fs).",
                epoch, 100 * share(ious, 0.5), statistics.median(ious), time.monotonic() - started,
            )  # fmt: skip
    return model.eval()


@torch.no_grad()
def box_ious(model: letters.BoxModel, samples: list[dict], device: str) -> list[float]:
    model.eval()
    ious = []
    for start in range(0, len(samples), 256):
        views, chars, gaps, target = box_batch(samples[start : start + 256], train=False, device=device)
        box, _ = model(views, chars, gaps)
        ious += overlap(box, target)[1].tolist()
    return ious


# ---------------------------------------------------------------- the classifier


def jittered(box: list[float]) -> list[float]:
    """An expert box moved and resized about as much as the box model's boxes differ from experts'."""
    x, y, width, height = box
    return [
        x + random.uniform(-0.12, 0.12) * width,
        y + random.uniform(-0.12, 0.12) * height,
        width * random.uniform(0.85, 1.2),
        height * random.uniform(0.85, 1.2),
    ]


def class_samples(pages, split: str, characters: dict[str, int], allographs: dict, pages_dir: Path) -> list[dict]:
    samples = []
    copies = CLASSIFIER_COPIES if split == "train" else 1
    for page in pages:
        if page["split"] != split:
            continue
        grey = Image.open(pages_dir / page["file"]).convert("L")
        for i, glyph in enumerate(page["boxes"]):
            label = allographs.get((glyph["character"], glyph["allograph"]), -100)
            j = page["pairs"].get(i)
            char = characters.get(page["anchors"][j].base, 0) if j is not None else 0
            for copy in range(copies):
                box = jittered(glyph["box"]) if copy else glyph["box"]
                aspect = box[2] / max(box[3], 1.0)
                samples.append({"view": letters.box_view(grey, box), "char": char, "aspect": aspect, "label": label})
    return samples


def class_batch(samples: list[dict], *, train: bool, device: str) -> tuple[torch.Tensor, ...]:
    views = [jitter_light(s["view"]) if train else s["view"] for s in samples]
    chars = [0 if train and random.random() < 0.1 else s["char"] for s in samples]
    return (
        letters.to_tensor(views).to(device),
        torch.tensor(chars).to(device),
        torch.tensor([[s["aspect"]] for s in samples], dtype=torch.float32).to(device),
        torch.tensor([s["label"] for s in samples]).to(device),
    )


def train_classifier(train: list[dict], validation: list[dict], characters: int, allographs: int, args):
    model = letters.Classifier(characters, allographs, pretrained=True).to(args.device)
    optimiser, scheduler = schedule(model, args.class_epochs * -(-len(train) // args.batch))
    started = time.monotonic()
    for epoch in range(1, args.class_epochs + 1):
        model.train()
        random.shuffle(train)
        for start in range(0, len(train), args.batch):
            batch = train[start : start + args.batch]
            views, chars, aspect, labels = class_batch(batch, train=True, device=args.device)
            loss = F.cross_entropy(model(views, chars, aspect), labels, ignore_index=-100, label_smoothing=0.1)
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            scheduler.step()
        if epoch % 5 == 0 or epoch == args.class_epochs:
            probabilities = classify(model, validation, args.device)
            labels = torch.tensor([s["label"] for s in validation])
            right = (probabilities.argmax(1) == labels).float().mean().item() if len(validation) else 0.0
            logger.info(
                "Classifier, epoch %d: on watched charters' expert boxes, %.1f%% right (%.0fs).",
                epoch, 100 * right, time.monotonic() - started,
            )  # fmt: skip
    return model.eval()


@torch.no_grad()
def classify(model: letters.Classifier, samples: list[dict], device: str) -> torch.Tensor:
    model.eval()
    out = [torch.zeros(0, model.head[-1].out_features)]
    for start in range(0, len(samples), 256):
        views, chars, aspect, _ = class_batch(samples[start : start + 256], train=False, device=device)
        out.append(model(views, chars, aspect).softmax(1).cpu())
    return torch.cat(out)


# ---------------------------------------------------------------- scoring


def share(values: list[float], at_least: float) -> float:
    return sum(v >= at_least for v in values) / len(values) if values else 0.0


def best_overlaps(box: list[float], boxes: np.ndarray) -> np.ndarray:
    x, y, width, height = box
    ix = np.clip(np.minimum(boxes[:, 0] + boxes[:, 2], x + width) - np.maximum(boxes[:, 0], x), 0, None)
    iy = np.clip(np.minimum(boxes[:, 1] + boxes[:, 3], y + height) - np.maximum(boxes[:, 1], y), 0, None)
    inter = ix * iy
    return inter / (boxes[:, 2] * boxes[:, 3] + width * height - inter)


def size_prior(pages: list[dict[str, Any]]):
    """The box baseline: each character's median expert box, in line-heights, about where it was read."""
    seen = defaultdict(list)
    for page in pages:
        if page["split"] != "train":
            continue
        for i, j in page["pairs"].items():
            a, (x, y, width, height) = page["anchors"][j], page["boxes"][i]["box"]
            h = a.line_height
            seen[a.base].append(((x + width / 2 - a.x) / h, (y + height / 2 - a.y) / h, width / h, height / h))
    everything = [v for values in seen.values() for v in values]
    fallback = [statistics.median(v[k] for v in everything) for k in range(4)]
    medians = {c: [statistics.median(v[k] for v in vs) for k in range(4)] for c, vs in seen.items() if len(vs) >= 5}

    def boxes(found: list[letters.Anchor]) -> list[list[float]]:
        out = []
        for a in found:
            dx, dy, width, height = medians.get(a.base, fallback)
            h = a.line_height
            out.append([a.x + dx * h - width * h / 2, a.y + dy * h - height * h / 2, width * h, height * h])
        return out

    return boxes


@torch.no_grad()
def draw(grey: Image.Image, found: list[letters.Anchor], box_model, characters, device) -> tuple[list, list[float]]:
    """The box the model draws round each character read, and how well it expects it to fit."""
    drawn, fits = [], []
    for start in range(0, len(found), 256):
        batch = found[start : start + 256]
        views = letters.to_tensor([letters.window(grey, a) for a in batch]).to(device)
        chars = torch.tensor([characters.get(a.base, 0) for a in batch]).to(device)
        gaps = torch.tensor([a.gaps for a in batch], dtype=torch.float32).to(device)
        fractions, fit = box_model(views, chars, gaps)
        drawn += [letters.box_from_window(f, a) for f, a in zip(fractions.tolist(), batch, strict=True)]
        fits += fit.tolist()
    return drawn, fits


def box_by_fit(pages, split: str, box_model, characters, args) -> list[dict[str, float]]:
    """How often a box with a given expected fit lands on the expert's, for the character read inside it."""
    outcomes: list[tuple[float, bool]] = []
    for page in pages:
        if page["split"] != split or not page["pairs"]:
            continue
        grey = Image.open(Path(args.pages) / page["file"]).convert("L")
        paired = list(page["pairs"].items())
        drawn, fits = draw(grey, [page["anchors"][j] for _, j in paired], box_model, characters, args.device)
        for (i, _), box, fit in zip(paired, drawn, fits, strict=True):
            outcomes.append((fit, bool(best_overlaps(page["boxes"][i]["box"], np.array([box]))[0] >= 0.5)))
    return [
        {
            "at_least": t,
            "share": round(share([f for f, _ in outcomes], t), 4),
            "iou_at_least_half": round(statistics.mean([ok for f, ok in outcomes if f >= t] or [0]), 4),
        }
        for t in FIT_THRESHOLDS
    ]


@torch.no_grad()
def score(pages, box_model, classifier, characters, allographs, args) -> dict[str, Any]:
    """End to end on the held-out charters: every expert box against every box drawn on its page."""
    names = {k: v for v, k in allographs.items()}
    prior = size_prior(pages)
    commonest = defaultdict(Counter)
    for page in pages:
        if page["split"] == "train":
            for i, j in page["pairs"].items():
                glyph = page["boxes"][i]
                commonest[page["anchors"][j].base][(glyph["character"], glyph["allograph"])] += 1

    model_best, prior_best, inside = [], [], 0
    named = named_by_reading = 0
    calibration: list[tuple[float, bool]] = []
    pages_dir = Path(args.pages)
    for page in pages:
        if page["split"] != "test":
            continue
        inside += len(page["pairs"])
        found = page["anchors"]
        if not found:
            model_best += [0.0] * len(page["boxes"])
            prior_best += [0.0] * len(page["boxes"])
            continue
        grey = Image.open(pages_dir / page["file"]).convert("L")
        drawn, _ = draw(grey, found, box_model, characters, args.device)
        model_boxes, prior_boxes = np.array(drawn), np.array(prior(found))
        hits = []
        for glyph in page["boxes"]:
            overlaps = best_overlaps(glyph["box"], model_boxes)
            k = int(overlaps.argmax())
            model_best.append(float(overlaps[k]))
            prior_best.append(float(best_overlaps(glyph["box"], prior_boxes).max()))
            if overlaps[k] >= 0.5:
                hits.append((glyph, k))
        if not hits:
            continue
        samples = [
            {
                "view": letters.box_view(grey, drawn[k]),
                "char": characters.get(found[k].base, 0),
                "aspect": drawn[k][2] / max(drawn[k][3], 1.0),
                "label": -100,
            }
            for _, k in hits
        ]
        probabilities = classify(classifier, samples, args.device)
        for (glyph, k), p in zip(hits, probabilities, strict=True):
            truth = (glyph["character"], glyph["allograph"])
            right = names[int(p.argmax())] == truth
            named += right
            guess = commonest.get(found[k].base)
            named_by_reading += bool(guess) and guess.most_common(1)[0][0] == truth
            calibration.append((float(p.max()), right))

    total, hit = len(model_best), len(calibration)
    return {
        "held_out_boxes": total,
        "read_inside": round(inside / total, 4),
        "boxes": {
            "model": overlap_summary(model_best),
            "baseline_size_prior": overlap_summary(prior_best),
        },
        "allograph_on_found_boxes": {
            "found": hit,
            "model": round(named / hit, 4) if hit else None,
            "baseline_commonest_for_reading": round(named_by_reading / hit, 4) if hit else None,
            "by_probability": [
                {
                    "at_least": t,
                    "share": round(share([p for p, _ in calibration], t), 4),
                    "right": round(statistics.mean([ok for p, ok in calibration if p >= t] or [0]), 4),
                }
                for t in THRESHOLDS
            ],
        },
        "box_by_fit": box_by_fit(pages, "test", box_model, characters, args),
    }


def overlap_summary(best: list[float]) -> dict[str, float]:
    return {
        "iou_at_least_0.5": round(share(best, 0.5), 4),
        "iou_at_least_0.7": round(share(best, 0.7), 4),
        "iou_at_least_0.3": round(share(best, 0.3), 4),
        "median_iou": round(statistics.median(best), 4) if best else 0.0,
    }


# ---------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release", required=True)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--kraken-model", default=os.environ.get("HTR_MODEL_PATH", "/models/catmus-medieval.mlmodel"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--box-epochs", type=int, default=25)
    parser.add_argument("--class-epochs", type=int, default=30)
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    pages = load(args)
    characters = {"<unknown>": 0}
    allographs: dict[tuple[str, str], int] = {}
    for page in pages:
        if page["split"] == "train":
            for a in page["anchors"]:
                characters.setdefault(a.base, len(characters))
            for glyph in page["boxes"]:
                allographs.setdefault((glyph["character"], glyph["allograph"]), len(allographs))
    counts = Counter(page["split"] for page in pages)
    logger.info("Pages: %s; %d characters read, %d allographs named.", dict(counts), len(characters), len(allographs))

    pages_dir = Path(args.pages)
    box_model = train_box_model(
        box_samples(pages, "train", characters, pages_dir),
        box_samples(pages, "validation", characters, pages_dir),
        len(characters),
        args,
    )
    classifier = train_classifier(
        class_samples(pages, "train", characters, allographs, pages_dir),
        class_samples(pages, "validation", characters, allographs, pages_dir),
        len(characters),
        len(allographs),
        args,
    )
    scores = score(pages, box_model, classifier, characters, allographs, args)
    logger.info("Held-out charters: %s", json.dumps(scores, indent=1))
    # MIN_FIT is chosen from this one: the box model never trained on these charters, and they are not the test set.
    watched_fit = box_by_fit(pages, "validation", box_model, characters, args)
    logger.info("Watched charters, box by fit: %s", json.dumps(watched_fit))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    weights = out / "letters.pt"
    torch.save(
        {
            "characters": characters,
            "allographs": [list(pair) for pair in allographs],
            "box_model": {k: v.cpu() for k, v in box_model.state_dict().items()},
            "classifier": {k: v.cpu() for k, v in classifier.state_dict().items()},
        },
        weights,
    )
    release_manifest = json.loads((Path(args.release) / "manifest.json").read_text(encoding="utf-8"))
    manifest = {
        "name": "letters",
        "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
        "trained": datetime.now(UTC).isoformat(timespec="seconds"),
        "release": release_manifest.get("version"),
        "split": (
            "by_charter: trained on the release's training charters less a tenth watched; "
            "scored on its held-out charters"
        ),
        "pages": dict(counts),
        "reader": {
            "kraken_model": Path(args.kraken_model).name,
            "kraken_sha256": hashlib.sha256(Path(args.kraken_model).read_bytes()).hexdigest(),
            "read_side": letters.READ_SIDE,
        },
        "backbone": "ResNet-18, ImageNet weights from torchvision, fine-tuned",
        "epochs": {"box_model": args.box_epochs, "classifier": args.class_epochs},
        "seed": args.seed,
        "device": args.device,
        "held_out": scores,
        "watched": {"box_by_fit": watched_fit},
    }
    (out / "letters.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Wrote %s (%s).", weights, manifest["sha256"][:12])


if __name__ == "__main__":
    main()

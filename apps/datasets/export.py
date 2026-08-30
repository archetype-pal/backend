"""Building the glyph dataset release (AI programme W0.2).

This module builds the **pixel-free** release: box geometry, allograph labels
and IIIF region references, and no image data at all. That distinction is what
lets it ship before a single archive has been asked anything — geometry and a
region URI are our own annotation work plus a pointer, where a crop is a
reproduction of someone else's photograph. The crop release is the same code
plus pixels, and is gated on `rights.may_redistribute_crops` (W0.4).

Splits are computed here rather than left to whoever trains a model, because a
DOI freezes them: a published dataset whose splits can drift is not a benchmark.
They are grouped by charter and, separately, by repository — a random split of
glyph crops would put crops from the same parchment, ink and photograph on both
sides, and a model can score well by recognising the photograph.
"""

from collections import Counter
from dataclasses import dataclass, field
import hashlib
from typing import Any

from apps.annotations.models import Graph
from apps.manuscripts.iiif import get_iiif_region_from_geojson
from apps.manuscripts.services.rights import clearance_summary

# The DigiPal import parked orphaned images under a sentinel ItemPart; the search
# registry filters it for the same reason. It is not a charter and must not
# become a training group.
SENTINEL_ITEM_PART_ID = -1

# Below this, a per-class number is not worth publishing as a claim.
THIN_CLASS_THRESHOLD = 20


@dataclass
class GlyphRow:
    """One labelled glyph. Everything needed to fetch the crop, minus the crop."""

    graph_id: int
    item_part_id: int
    item_image_id: int
    repository: str
    allograph: str
    character: str
    hand_id: int | None
    iiif_region: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "item_part_id": self.item_part_id,
            "item_image_id": self.item_image_id,
            "repository": self.repository,
            "allograph": self.allograph,
            "character": self.character,
            # Hand, never scribe: 689 of 696 hands hang off a migration
            # placeholder, so a scribe column would publish a sentinel as a
            # label. Hands are also what MoA actually catalogued.
            "hand_id": self.hand_id,
            "iiif_region": self.iiif_region,
        }


@dataclass
class Splits:
    """Grouped splits, plus the rule that produced them."""

    by_charter: dict[str, list[int]] = field(default_factory=dict)
    by_repository: dict[str, list[str]] = field(default_factory=dict)


def collect_glyphs() -> list[GlyphRow]:
    """Every labelled glyph annotation, sentinel excluded."""
    queryset = (
        Graph.objects.filter(annotation_type=Graph.AnnotationType.IMAGE)
        .exclude(item_image__item_part_id=SENTINEL_ITEM_PART_ID)
        .values(
            "id",
            "annotation",
            "hand_id",
            "item_image_id",
            "item_image__item_part_id",
            "item_image__item_part__current_item__repository__label",
            "allograph__name",
            "allograph__character__name",
        )
    )
    rows = []
    for row in queryset.iterator(chunk_size=2000):
        rows.append(
            GlyphRow(
                graph_id=row["id"],
                item_part_id=row["item_image__item_part_id"],
                item_image_id=row["item_image_id"],
                repository=row["item_image__item_part__current_item__repository__label"] or "",
                allograph=row["allograph__name"] or "",
                character=row["allograph__character__name"] or "",
                hand_id=row["hand_id"],
                iiif_region=get_iiif_region_from_geojson(row["annotation"]),
            )
        )
    return rows


def class_support(rows: list[GlyphRow]) -> list[dict[str, Any]]:
    """Per-class counts, with the thin classes flagged rather than buried.

    Published beside any per-class number so a reader can see which classes
    cannot support a claim.
    """
    counts = Counter(row.allograph for row in rows if row.allograph)
    return [
        {"allograph": name, "examples": count, "thin": count < THIN_CLASS_THRESHOLD}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _bucket(key: str, folds: int) -> int:
    """Deterministic fold for *key*. Stable across runs, machines and releases."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % folds


def build_splits(rows: list[GlyphRow], *, holdout_fraction: int = 5) -> Splits:
    """Grouped splits: never by image, never by glyph.

    Charters carry several images each, so holding out a charter withholds a
    real group rather than a single page. The repository split is the control
    for the acquisition confound — it asks whether a model still works on an
    archive it has never seen.
    """
    charters = sorted({row.item_part_id for row in rows})
    held_out = [pk for pk in charters if _bucket(f"charter:{pk}", holdout_fraction) == 0]
    by_charter = {
        "train": [pk for pk in charters if pk not in set(held_out)],
        "held_out": held_out,
    }

    repositories = sorted({row.repository for row in rows if row.repository})
    by_repository = {
        "train": [name for name in repositories if _bucket(f"repo:{name}", holdout_fraction) != 0],
        "held_out": [name for name in repositories if _bucket(f"repo:{name}", holdout_fraction) == 0],
    }
    return Splits(by_charter=by_charter, by_repository=by_repository)


def build_manifest(rows: list[GlyphRow], splits: Splits, *, version: str) -> dict[str, Any]:
    """The release's own description of what it is, and what it is not."""
    charters = {row.item_part_id for row in rows}
    images = {row.item_image_id for row in rows}
    hands = {row.hand_id for row in rows if row.hand_id}
    clearance = clearance_summary()
    holding = [row for row in clearance if row.images]

    return {
        "name": "archetype-glyphs-pixel-free",
        "version": version,
        "contains": (
            "Bounding-box geometry, allograph labels, hand identifiers and IIIF region "
            "references for every expert-annotated glyph in the corpus."
        ),
        "contains_no_pixels": True,
        "why_no_pixels": (
            "The images are the holding repositories' photography. Geometry and a region "
            "reference are our own annotation work plus a pointer, so this release needs no "
            "clearance; a crop release reproduces their images and does. See rights below."
        ),
        "counts": {
            "glyphs": len(rows),
            "charters": len(charters),
            "images": len(images),
            "hands": len(hands),
            "allograph_classes": len({row.allograph for row in rows if row.allograph}),
        },
        "excluded": {
            "sentinel_item_part": SENTINEL_ITEM_PART_ID,
            "why": "A DigiPal-import placeholder that parks orphaned images; not a charter.",
            "scribe_labels": (
                "Not exported. Almost every hand hangs off a migration placeholder scribe, so a "
                "scribe column would publish a sentinel as ground truth."
            ),
        },
        "splits": {
            "rule": "Grouped by charter; never by image, never by glyph. Second split held out by repository.",
            "deterministic": "Fold = sha256(key) mod folds, so the split is reproducible from this manifest alone.",
            "charters_held_out": len(splits.by_charter.get("held_out", [])),
            "repositories_held_out": splits.by_repository.get("held_out", []),
        },
        "rights": {
            "images_cleared_for_crop_redistribution": sum(row.images for row in clearance if row.cleared),
            "images_total": sum(row.images for row in clearance),
            "repositories_holding_images": len(holding),
            "uncleared_repositories": [row.repository for row in holding if not row.cleared],
        },
        "how_to_re_derive": "manage.py export_glyph_dataset --out <dir> --release <version>",
    }

"""The pixel-free glyph dataset release — AI programme W0.2.

The properties worth pinning are the ones a DOI freezes: the release contains no
pixels, the splits are grouped and reproducible, and the sentinel and the
placeholder scribe never reach a published label.
"""

import json
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.datasets import export
from apps.manuscripts.models import Repository
from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory, RepositoryFactory

BOX = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[10, 10], [30, 10], [30, 40], [10, 40], [10, 10]]]},
    "properties": {},
}


def _glyph(**kwargs):
    return GraphFactory(annotation=BOX, annotation_type=Graph.AnnotationType.IMAGE, **kwargs)


@pytest.mark.django_db
class TestCollection:
    def test_collects_labelled_glyphs_with_a_region_reference(self):
        _glyph()

        rows = export.collect_glyphs()

        assert len(rows) == 1
        assert rows[0].iiif_region != "full"

    def test_text_regions_are_not_glyphs(self):
        GraphFactory(annotation=BOX, annotation_type=Graph.AnnotationType.TEXT)

        assert export.collect_glyphs() == []

    def test_the_import_sentinel_is_excluded(self):
        """The DigiPal placeholder parks orphaned images; it is not a charter."""
        sentinel = ItemPartFactory(id=export.SENTINEL_ITEM_PART_ID)
        _glyph(item_image=ItemImageFactory(item_part=sentinel))

        assert export.collect_glyphs() == []

    def test_no_row_carries_a_scribe_label(self):
        _glyph()

        payload = export.collect_glyphs()[0].as_dict()

        assert "hand_id" in payload
        assert not any("scribe" in key for key in payload)


@pytest.mark.django_db
class TestClassSupport:
    def test_thin_classes_are_flagged_not_buried(self):
        """18 real classes have fewer than 20 examples; a reader must see which."""
        _glyph()

        support = export.class_support(export.collect_glyphs())

        assert support[0]["examples"] == 1
        assert support[0]["thin"] is True


@pytest.mark.django_db
class TestSplits:
    def test_splits_group_by_charter_never_by_glyph(self):
        part = ItemPartFactory()
        image = ItemImageFactory(item_part=part)
        _glyph(item_image=image)
        _glyph(item_image=image)

        splits = export.build_splits(export.collect_glyphs())
        placed = set(splits.by_charter["train"]) | set(splits.by_charter["held_out"])

        assert placed == {part.pk}

    def test_a_charter_is_never_on_both_sides(self):
        for _ in range(25):
            _glyph()

        splits = export.build_splits(export.collect_glyphs())

        assert not set(splits.by_charter["train"]) & set(splits.by_charter["held_out"])

    def test_the_split_is_reproducible(self):
        """A DOI freezes the split; it must not drift between runs."""
        for _ in range(10):
            _glyph()
        rows = export.collect_glyphs()

        assert export.build_splits(rows).by_charter == export.build_splits(rows).by_charter


@pytest.mark.django_db
class TestManifest:
    def test_declares_that_it_carries_no_pixels(self):
        _glyph()
        rows = export.collect_glyphs()

        manifest = export.build_manifest(rows, export.build_splits(rows), version="v1")

        assert manifest["contains_no_pixels"] is True
        assert "clearance" in manifest["why_no_pixels"]

    def test_reports_the_crop_clearance_a_pixel_release_would_need(self):
        repository = RepositoryFactory(derivative_release=Repository.DerivativeRelease.UNKNOWN)
        _glyph(item_image=ItemImageFactory(item_part=ItemPartFactory(current_item__repository=repository)))
        rows = export.collect_glyphs()

        manifest = export.build_manifest(rows, export.build_splits(rows), version="v1")

        assert manifest["rights"]["images_cleared_for_crop_redistribution"] == 0
        assert repository.label in manifest["rights"]["uncleared_repositories"]


@pytest.mark.django_db
class TestCommand:
    def test_writes_the_four_release_files(self, tmp_path: Path):
        _glyph()

        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1")

        release = tmp_path / "v1"
        assert {p.name for p in release.iterdir()} == {
            "glyphs.jsonl",
            "allographs.json",
            "splits.json",
            "manifest.json",
        }
        line = json.loads((release / "glyphs.jsonl").read_text().splitlines()[0])
        assert set(line) == {
            "graph_id",
            "item_part_id",
            "item_image_id",
            "repository",
            "allograph",
            "character",
            "hand_id",
            "iiif_region",
        }

    def test_refuses_to_overwrite_a_published_version(self, tmp_path: Path):
        _glyph()
        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1")

        with pytest.raises(CommandError, match="already exists"):
            call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1")

    def test_force_overwrites(self, tmp_path: Path):
        _glyph()
        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1")

        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1", "--force")

    def test_an_empty_corpus_is_an_error_not_an_empty_release(self, tmp_path: Path):
        with pytest.raises(CommandError, match="nothing to export"):
            call_command("export_glyph_dataset", "--out", str(tmp_path))

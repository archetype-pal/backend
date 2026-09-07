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
    def test_regions_are_converted_from_y_up_rings_to_iiif_coordinates(self, monkeypatch):
        """The stored rings are Y-up; IIIF is Y-down. Publishing the raw ring
        mirrors every glyph about the page's midline, and a DOI freezes it."""
        _glyph()
        monkeypatch.setattr(export, "image_heights", lambda ids: ({i: 4000 for i in ids}, []))

        rows = export.collect_glyphs()

        # ring y spans 10..40 on a 4000px page -> IIIF y = 4000 - 10 - 30
        assert rows[0].iiif_region == "10,3960,20,30"

    def test_a_region_is_null_when_the_page_height_is_unknown(self, monkeypatch):
        """A guessed height yields a plausible, wrong coordinate; null is honest."""
        _glyph()
        monkeypatch.setattr(export, "image_heights", lambda ids: ({}, list(ids)))

        rows = export.collect_glyphs()

        assert rows[0].iiif_region is None
        assert export.unlocated(rows) == rows

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

    def test_both_sides_of_the_split_are_populated(self):
        """A split that holds out nothing is not a split, and would pass every
        other assertion here."""
        for _ in range(40):
            _glyph()

        splits = export.build_splits(export.collect_glyphs())

        assert splits.by_charter["train"]
        assert splits.by_charter["held_out"]

    def test_the_fold_is_content_addressed_not_process_seeded(self):
        """Python's hash() is salted per process; a split seeded on it would
        differ between the run that published a DOI and every run after."""
        assert export._bucket("charter:1", 5) == export._bucket("charter:1", 5)
        # Value pinned so a change of hashing algorithm is a visible decision.
        assert export._bucket("charter:1", 5) == 3

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
    def test_writes_the_release_files(self, tmp_path: Path):
        _glyph()

        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1", "--allow-unlocated")

        release = tmp_path / "v1"
        assert {p.name for p in release.iterdir()} == {
            "glyphs.jsonl",
            "allographs.json",
            "splits.json",
            "manifest.json",
            "LICENSE.txt",
        }
        licence = (release / "LICENSE.txt").read_text()
        assert "CC-BY-4.0" in licence
        # The images are not ours to license, and the notice must say so.
        assert "contains no image data" in licence
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
        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1", "--allow-unlocated")

        with pytest.raises(CommandError, match="already exists"):
            call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1", "--allow-unlocated")

    def test_force_overwrites(self, tmp_path: Path):
        _glyph()
        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1", "--allow-unlocated")

        call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1", "--force", "--allow-unlocated")

    def test_refuses_to_publish_regions_it_could_not_locate(self, tmp_path):
        """A DOI freezes whatever ships, so a mirrored region must not ship."""
        _glyph()

        with pytest.raises(CommandError, match="no locatable IIIF region"):
            call_command("export_glyph_dataset", "--out", str(tmp_path), "--release", "v1")

    def test_an_empty_corpus_is_an_error_not_an_empty_release(self, tmp_path: Path):
        with pytest.raises(CommandError, match="nothing to export"):
            call_command("export_glyph_dataset", "--out", str(tmp_path))

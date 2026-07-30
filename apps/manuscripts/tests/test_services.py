"""Tests for apps.manuscripts.services.

Targets build_item_parts_detail, a nested-dict builder.
"""

import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.services import build_item_parts_detail
from apps.manuscripts.tests.factories import (
    CurrentItemFactory,
    HistoricalItemFactory,
    ImageTextFactory,
    ItemImageFactory,
    ItemPartFactory,
    RepositoryFactory,
)


@pytest.mark.django_db
class TestBuildItemPartsDetail:
    def test_returns_empty_list_when_historical_item_has_no_parts(self):
        hi = HistoricalItemFactory()
        assert build_item_parts_detail(hi) == []

    def test_returns_one_entry_per_item_part(self):
        hi = HistoricalItemFactory()
        ItemPartFactory(historical_item=hi)
        ItemPartFactory(historical_item=hi)
        result = build_item_parts_detail(hi)
        assert len(result) == 2

    def test_entry_contract_includes_all_documented_fields(self):
        hi = HistoricalItemFactory()
        repo = RepositoryFactory()
        ci = CurrentItemFactory(repository=repo, shelfmark="MS 12345")
        part = ItemPartFactory(historical_item=hi, current_item=ci)

        [entry] = build_item_parts_detail(hi)

        expected_keys = {
            "id",
            "custom_label",
            "current_item",
            "current_item_display",
            "current_item_locus",
            "display_label",
            "repository",
            "repository_name",
            "shelfmark",
            "images",
            "msdesc_areas",
        }
        assert set(entry.keys()) == expected_keys
        assert entry["id"] == part.id
        assert entry["current_item"] == ci.id
        assert entry["repository"] == repo.id
        assert entry["repository_name"] == repo.label
        assert entry["shelfmark"] == "MS 12345"
        assert entry["images"] == []
        assert entry["msdesc_areas"] == []

    def test_handles_part_with_no_current_item(self):
        """A part can exist without a current_item (NULLable FK)."""
        hi = HistoricalItemFactory()
        ItemPartFactory(historical_item=hi, current_item=None)
        [entry] = build_item_parts_detail(hi)
        # Repository chain collapses gracefully — every dependent field is None.
        assert entry["current_item"] is None
        assert entry["current_item_display"] is None
        assert entry["repository"] is None
        assert entry["repository_name"] is None
        assert entry["shelfmark"] is None

    def test_image_text_count_is_correct_per_image(self):
        hi = HistoricalItemFactory()
        part = ItemPartFactory(historical_item=hi)
        # ImageText has a unique constraint on (item_image_id, type); per image we
        # can have at most one of each type. Two types → max two texts per image.
        img_with_two = ItemImageFactory(item_part=part)
        img_with_one = ItemImageFactory(item_part=part)
        ItemImageFactory(item_part=part)  # zero texts
        ImageTextFactory(item_image=img_with_two, type=ImageText.Type.TRANSCRIPTION)
        ImageTextFactory(item_image=img_with_two, type=ImageText.Type.TRANSLATION)
        ImageTextFactory(item_image=img_with_one, type=ImageText.Type.TRANSCRIPTION)

        [entry] = build_item_parts_detail(hi)
        counts_by_id = {img["id"]: img["text_count"] for img in entry["images"]}

        assert counts_by_id[img_with_two.id] == 2
        assert counts_by_id[img_with_one.id] == 1
        assert sum(1 for c in counts_by_id.values() if c == 0) == 1

    def test_image_entry_contract(self):
        hi = HistoricalItemFactory()
        part = ItemPartFactory(historical_item=hi)
        ItemImageFactory(item_part=part, locus="fol. 3r")

        [entry] = build_item_parts_detail(hi)
        [image_entry] = entry["images"]

        assert set(image_entry.keys()) == {"id", "image", "locus", "text_count"}
        assert image_entry["locus"] == "fol. 3r"
        assert image_entry["text_count"] == 0

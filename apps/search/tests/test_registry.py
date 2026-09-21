"""What `get_queryset_for_index` feeds each index — including what it withholds."""

import pytest

from apps.manuscripts.models import HistoricalItem, ImageText, ItemImage, ItemPart
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.scribes.models import Scribe
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.types import IndexType

TEXT_DERIVED_INDEXES = [IndexType.TEXTS, IndexType.CLAUSES, IndexType.PEOPLE, IndexType.PLACES]
OTHER_INDEXES = [
    IndexType.ITEM_PARTS,
    IndexType.ITEM_IMAGES,
    IndexType.GRAPHS,
    IndexType.HANDS,
    IndexType.SCRIBES,
]


@pytest.fixture
def one_text_per_status(db):
    """One ImageText per status. Four rows need two images: a unique constraint
    allows only one text per (image, type)."""
    image_a = ItemImageFactory()
    image_b = ItemImageFactory()
    return {
        ImageText.Status.LIVE: ImageTextFactory(
            item_image=image_a, type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE
        ),
        ImageText.Status.REVIEWED: ImageTextFactory(
            item_image=image_a, type=ImageText.Type.TRANSLATION, status=ImageText.Status.REVIEWED
        ),
        ImageText.Status.DRAFT: ImageTextFactory(
            item_image=image_b, type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.DRAFT
        ),
        ImageText.Status.REVIEW: ImageTextFactory(
            item_image=image_b, type=ImageText.Type.TRANSLATION, status=ImageText.Status.REVIEW
        ),
    }


def indexed_pks(index_type: IndexType) -> set:
    return set(get_queryset_for_index(index_type).values_list("pk", flat=True))


@pytest.mark.django_db
class TestIndexQuerysets:
    def test_an_index_is_backed_by_its_registered_model(self):
        assert get_queryset_for_index(IndexType.ITEM_PARTS).model is ItemPart
        assert get_queryset_for_index(IndexType.SCRIBES).model is Scribe
        assert get_queryset_for_index(IndexType.ITEM_PARTS).ordered


@pytest.mark.django_db
class TestLegacyNullSentinelIsExcluded:
    def test_item_parts_exclude_the_sentinel_row(self):
        historical_item = HistoricalItem.objects.create(type="charter")
        ItemPart.objects.create(pk=-1, historical_item=historical_item, custom_label="Created for all the nulls")
        real = ItemPart.objects.create(historical_item=historical_item)

        assert indexed_pks(IndexType.ITEM_PARTS) == {real.pk}

    def test_item_images_exclude_images_parked_on_the_sentinel(self):
        historical_item = HistoricalItem.objects.create(type="charter")
        sentinel = ItemPart.objects.create(pk=-1, historical_item=historical_item)
        real = ItemPart.objects.create(historical_item=historical_item)
        ItemImage.objects.create(item_part=sentinel, image="orphan.jp2")
        kept = ItemImage.objects.create(item_part=real, image="kept.jp2")

        assert indexed_pks(IndexType.ITEM_IMAGES) == {kept.pk}


@pytest.mark.django_db
class TestOnlyPublicImageTextsAreIndexed:
    """Draft image-texts must never enter the public index (#213). Enforced at
    build time, so the search endpoints have nothing to leak."""

    @pytest.mark.parametrize("index_type", TEXT_DERIVED_INDEXES)
    def test_draft_and_review_rows_are_excluded(self, index_type, one_text_per_status):
        assert indexed_pks(index_type) == {
            one_text_per_status[ImageText.Status.LIVE].pk,
            one_text_per_status[ImageText.Status.REVIEWED].pk,
        }

    @pytest.mark.parametrize("index_type", TEXT_DERIVED_INDEXES)
    def test_a_text_leaving_draft_becomes_indexable(self, index_type, one_text_per_status):
        draft = one_text_per_status[ImageText.Status.DRAFT]
        draft.status = ImageText.Status.LIVE
        draft.save(update_fields=["status"])

        assert draft.pk in indexed_pks(index_type)

    @pytest.mark.parametrize("index_type", TEXT_DERIVED_INDEXES)
    def test_a_text_returned_to_draft_stops_being_indexable(self, index_type, one_text_per_status):
        live = one_text_per_status[ImageText.Status.LIVE]
        live.status = ImageText.Status.DRAFT
        live.save(update_fields=["status"])

        assert live.pk not in indexed_pks(index_type)

    @pytest.mark.parametrize("index_type", OTHER_INDEXES)
    def test_indexes_without_a_status_field_are_untouched(self, index_type, one_text_per_status):
        assert "status__in" not in (get_registration(index_type).queryset_filter or {})
        list(get_queryset_for_index(index_type)[:1])

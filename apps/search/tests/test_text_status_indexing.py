"""Draft image-texts must never enter the public search index (#213).

Enforced at index-build time: the four ImageText-derived indexes only ever see
Live and Reviewed rows, so search cannot serve a draft even in principle. The
search endpoints themselves stay status-blind — they simply have nothing to
leak.
"""

import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.search.registry import get_queryset_for_index, get_registration
from apps.search.types import IndexType

TEXT_DERIVED_INDEXES = [
    IndexType.TEXTS,
    IndexType.CLAUSES,
    IndexType.PEOPLE,
    IndexType.PLACES,
]


@pytest.fixture
def one_text_per_status(db):
    """One ImageText in each status, spread over images.

    A unique constraint allows only one text per (image, type), so four rows
    need two images.
    """
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


@pytest.mark.django_db
class TestTextDerivedIndexesOnlyBuildFromPublicRows:
    @pytest.mark.parametrize("index_type", TEXT_DERIVED_INDEXES)
    def test_draft_and_review_rows_are_excluded(self, index_type, one_text_per_status):
        indexed = set(get_queryset_for_index(index_type).values_list("pk", flat=True))

        assert indexed == {
            one_text_per_status[ImageText.Status.LIVE].pk,
            one_text_per_status[ImageText.Status.REVIEWED].pk,
        }

    @pytest.mark.parametrize("index_type", TEXT_DERIVED_INDEXES)
    def test_a_text_leaving_draft_becomes_indexable(self, index_type, one_text_per_status):
        draft = one_text_per_status[ImageText.Status.DRAFT]
        draft.status = ImageText.Status.LIVE
        draft.save(update_fields=["status"])

        assert draft.pk in set(get_queryset_for_index(index_type).values_list("pk", flat=True))

    @pytest.mark.parametrize("index_type", TEXT_DERIVED_INDEXES)
    def test_a_text_returned_to_draft_stops_being_indexable(self, index_type, one_text_per_status):
        # Note this only takes effect on the next reindex: these indexes have no
        # incremental sync, so an unpublished text stays in the live index until
        # one is run.
        live = one_text_per_status[ImageText.Status.LIVE]
        live.status = ImageText.Status.DRAFT
        live.save(update_fields=["status"])

        assert live.pk not in set(get_queryset_for_index(index_type).values_list("pk", flat=True))

    @pytest.mark.parametrize(
        "index_type",
        [IndexType.ITEM_PARTS, IndexType.ITEM_IMAGES, IndexType.GRAPHS, IndexType.HANDS, IndexType.SCRIBES],
    )
    def test_indexes_not_derived_from_image_text_are_unaffected(self, index_type, one_text_per_status):
        # The status filter is scoped to the four ImageText-derived indexes —
        # those models have no `status`, so applying it would raise FieldError.
        assert "status__in" not in (get_registration(index_type).queryset_filter or {})
        list(get_queryset_for_index(index_type)[:1])

"""The dashboard's in-sync check: expected document counts per index, from real rows."""

from unittest.mock import patch

from django.core.cache import cache
import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemPartFactory
from apps.search.admin_service import SearchAdminService
from apps.search.types import IndexType

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_count_cache():
    cache.clear()


def _stats(meilisearch_counts: dict[IndexType, int]) -> dict[str, dict]:
    with patch("apps.search.admin_service.MeilisearchIndexWriter") as writer_cls:
        writer_cls.return_value.get_stats.side_effect = lambda index_type: {
            "numberOfDocuments": meilisearch_counts.get(index_type, 0)
        }
        return {entry["index_type"]: entry for entry in SearchAdminService().get_index_stats_list()}


def test_fan_out_indexes_count_the_documents_each_text_produces():
    ImageTextFactory(
        status=ImageText.Status.LIVE,
        content='<p><seg type="address" corresp="#gid-1">A</seg><seg type="salutation">B</seg>'
        "<persName>Alice</persName><persName>Bob</persName><placeName>Paris</placeName></p>",
    )
    ImageTextFactory(status=ImageText.Status.LIVE, content='<p><seg type="disposition">C</seg></p>')
    ImageTextFactory(status=ImageText.Status.DRAFT, content='<p><seg type="x">not public</seg></p>')

    stats = _stats({IndexType.CLAUSES: 3, IndexType.PEOPLE: 2, IndexType.PLACES: 0})

    assert (stats["clauses"]["db_count"], stats["clauses"]["in_sync"]) == (3, True)
    assert (stats["people"]["db_count"], stats["people"]["in_sync"]) == (2, True)
    assert (stats["places"]["db_count"], stats["places"]["in_sync"]) == (1, False)
    assert stats["texts"]["db_count"] == 2


def test_one_to_one_indexes_count_rows():
    ItemPartFactory.create_batch(2)

    stats = _stats({IndexType.ITEM_PARTS: 3})

    assert (stats["item-parts"]["db_count"], stats["item-parts"]["in_sync"]) == (2, False)

from unittest.mock import MagicMock, patch

from apps.search.admin_service import SearchAdminService
from apps.search.types import IndexType


class _FakeValuesList:
    def __init__(self, values):
        self._values = values

    def iterator(self, chunk_size=500):
        return iter(self._values)


class _FakeQuerySet:
    def __init__(self, *, count_value=0, contents=None):
        self._count_value = count_value
        self._contents = contents or []

    def count(self):
        return self._count_value

    def values_list(self, field, flat=False):
        assert field == "content"
        assert flat is True
        return _FakeValuesList(self._contents)


def _build_writer_mock(counts: dict[IndexType, int]) -> MagicMock:
    writer = MagicMock()
    writer.get_stats.side_effect = lambda index_type: {
        "numberOfDocuments": counts.get(index_type, 0),
    }
    return writer


@patch("apps.search.admin_service.get_queryset_for_index")
@patch("apps.search.admin_service.MeilisearchIndexWriter")
def test_get_index_stats_list_counts_dpt_fragments_for_one_to_many_indexes(
    writer_cls_mock: MagicMock, queryset_mock: MagicMock
):
    writer_cls_mock.return_value = _build_writer_mock(
        {
            IndexType.CLAUSES: 3,
            IndexType.PEOPLE: 2,
            IndexType.PLACES: 1,
        }
    )

    by_type = {
        IndexType.CLAUSES: _FakeQuerySet(
            contents=[
                '<span data-dpt="clause">A</span><span data-dpt="clause">B</span>',
                '<span data-dpt="clause">C</span>',
            ]
        ),
        IndexType.PEOPLE: _FakeQuerySet(
            contents=[
                '<span data-dpt="person">Alice</span><span data-dpt="person">Bob</span>',
            ]
        ),
        IndexType.PLACES: _FakeQuerySet(contents=['<span data-dpt="place">Paris</span>']),
    }

    queryset_mock.side_effect = lambda index_type: by_type.get(index_type, _FakeQuerySet(count_value=0))

    stats = SearchAdminService().get_index_stats_list()
    stats_by_segment = {entry["index_type"]: entry for entry in stats}

    assert stats_by_segment["clauses"]["db_count"] == 3
    assert stats_by_segment["people"]["db_count"] == 2
    assert stats_by_segment["places"]["db_count"] == 1
    assert stats_by_segment["clauses"]["in_sync"] is True
    assert stats_by_segment["people"]["in_sync"] is True
    assert stats_by_segment["places"]["in_sync"] is True


@patch("apps.search.admin_service.get_queryset_for_index")
@patch("apps.search.admin_service.MeilisearchIndexWriter")
def test_get_index_stats_list_uses_queryset_count_for_one_to_one_indexes(
    writer_cls_mock: MagicMock, queryset_mock: MagicMock
):
    writer_cls_mock.return_value = _build_writer_mock({IndexType.ITEM_PARTS: 10})
    queryset_mock.side_effect = lambda index_type: (
        _FakeQuerySet(count_value=8) if index_type == IndexType.ITEM_PARTS else _FakeQuerySet(count_value=0)
    )

    stats = SearchAdminService().get_index_stats_list()
    stats_by_segment = {entry["index_type"]: entry for entry in stats}

    assert stats_by_segment["item-parts"]["db_count"] == 8
    assert stats_by_segment["item-parts"]["in_sync"] is False

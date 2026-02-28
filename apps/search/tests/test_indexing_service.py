from types import SimpleNamespace
from unittest.mock import MagicMock

from apps.search.services import IndexingService
from apps.search.types import IndexType


class _FakeQuerySet:
    def __init__(self, items):
        self._items = list(items)

    def count(self):
        return len(self._items)

    def iterator(self, chunk_size=500):
        del chunk_size
        yield from self._items


def test_reindex_uses_builder_iterable_contract(monkeypatch, db):
    del db
    fake_writer = MagicMock()
    service = IndexingService(writer=fake_writer)

    fake_registration = SimpleNamespace(
        builder=lambda obj: ({"id": obj["id"]}, {"id": obj["id"] + 100}),
    )
    monkeypatch.setattr(
        "apps.search.services.get_registration",
        lambda index_type: fake_registration if index_type == IndexType.ITEM_PARTS else None,
    )
    monkeypatch.setattr(
        "apps.search.services.get_queryset_for_index",
        lambda index_type: _FakeQuerySet([{"id": 1}, {"id": 2}]),
    )

    processed = service.reindex(IndexType.ITEM_PARTS)

    assert processed == 2
    fake_writer.ensure_index_and_settings.assert_called_once_with(IndexType.ITEM_PARTS)
    fake_writer.delete_all.assert_called_once_with(IndexType.ITEM_PARTS)
    fake_writer.add_documents_batch.assert_called_once_with(
        IndexType.ITEM_PARTS,
        [{"id": 1}, {"id": 101}, {"id": 2}, {"id": 102}],
    )

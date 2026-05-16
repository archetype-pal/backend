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
    # Atomic reindex pattern (P1.3): build into staging index, swap, drop old.
    fake_writer.prepare_build_index.assert_called_once_with(IndexType.ITEM_PARTS)
    fake_writer.add_documents_to_build.assert_called_once_with(
        IndexType.ITEM_PARTS,
        [{"id": 1}, {"id": 101}, {"id": 2}, {"id": 102}],
    )
    fake_writer.swap_with_build.assert_called_once_with(IndexType.ITEM_PARTS)
    fake_writer.drop_build_index.assert_called_once_with(IndexType.ITEM_PARTS)
    # delete_all must NOT be called — that's the old non-atomic pattern.
    fake_writer.delete_all.assert_not_called()


def test_reindex_swap_happens_after_all_batches(monkeypatch, db):
    """Regression test: swap must occur strictly after all documents are written,
    otherwise readers see a partial index for the duration of the reindex."""
    del db
    call_order: list[str] = []
    fake_writer = MagicMock()
    fake_writer.add_documents_to_build.side_effect = lambda *_args, **_kw: call_order.append("write")
    fake_writer.swap_with_build.side_effect = lambda *_args, **_kw: call_order.append("swap")

    monkeypatch.setattr(
        "apps.search.services.get_registration",
        lambda index_type: (
            SimpleNamespace(builder=lambda obj: ({"id": obj["id"]},)) if index_type == IndexType.ITEM_PARTS else None
        ),
    )
    monkeypatch.setattr(
        "apps.search.services.get_queryset_for_index",
        lambda index_type: _FakeQuerySet([{"id": 1}, {"id": 2}, {"id": 3}]),
    )

    IndexingService(writer=fake_writer).reindex(IndexType.ITEM_PARTS)

    # Single batch in this fake, but the ordering invariant is: every "write" comes
    # before "swap" — never interleaved.
    assert "swap" in call_order
    assert call_order.index("swap") == len(call_order) - 1, f"swap must be last; got order: {call_order}"

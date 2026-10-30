"""The Celery tasks are thin wrappers; what matters is the result payload the dashboard poll reads."""

from unittest.mock import MagicMock

import pytest

from apps.search.tasks import clear_search_index, reindex_all_search_indexes, reindex_search_index
from apps.search.types import IndexType


@pytest.fixture
def indexing(monkeypatch):
    service = MagicMock()
    service.reindex.return_value = 5
    service.reindex_all.return_value = {"item-parts": 2, "scribes": 3}
    monkeypatch.setattr("apps.search.tasks.IndexingService", lambda: service)
    for task in (reindex_search_index, reindex_all_search_indexes):
        monkeypatch.setattr(task, "update_state", lambda *args, **kwargs: None)
    return service


def test_task_payloads(indexing):
    assert reindex_search_index.run("item-parts") == {"action": "reindex", "index_type": "item-parts", "indexed": 5}
    assert indexing.reindex.call_args.args == (IndexType.ITEM_PARTS,)

    assert clear_search_index.run("item-parts") == {"action": "clear", "index_type": "item-parts"}
    indexing.clear.assert_called_once_with(IndexType.ITEM_PARTS)

    assert reindex_all_search_indexes.run() == {"action": "reindex_all", "indexed": 5}

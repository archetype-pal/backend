"""The Celery tasks are thin wrappers; what matters is the result payload the dashboard poll reads."""

from unittest.mock import MagicMock

import pytest

from apps.search.tasks import (
    clear_search_index,
    delete_search_documents,
    reindex_search_index,
    sync_search_documents,
)
from apps.search.types import IndexType


@pytest.fixture
def indexing(monkeypatch):
    service = MagicMock()
    service.reindex.return_value = 5
    service.update_documents_by_ids.return_value = 2
    monkeypatch.setattr("apps.search.tasks.IndexingService", lambda: service)
    monkeypatch.setattr(reindex_search_index, "update_state", lambda *args, **kwargs: None)
    return service


def test_task_payloads(indexing):
    assert reindex_search_index.run("item-parts") == {"action": "reindex", "index_type": "item-parts", "indexed": 5}
    assert indexing.reindex.call_args.args == (IndexType.ITEM_PARTS,)

    assert clear_search_index.run("item-parts") == {"action": "clear", "index_type": "item-parts"}
    indexing.clear.assert_called_once_with(IndexType.ITEM_PARTS)


def test_incremental_task_payloads(indexing):
    result = sync_search_documents.run("graphs", [1, 2])
    assert result == {"action": "sync_documents", "index_type": "graphs", "indexed": 2, "pks": [1, 2]}
    indexing.update_documents_by_ids.assert_called_once_with(IndexType.GRAPHS, [1, 2])

    result = delete_search_documents.run("graphs", [5])
    assert result == {"action": "delete_documents", "index_type": "graphs", "pks": [5]}
    indexing.delete_documents_by_ids.assert_called_once_with(IndexType.GRAPHS, [5])

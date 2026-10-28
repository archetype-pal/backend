from unittest.mock import MagicMock

from apps.search.tasks import clear_search_index, reindex_all_search_indexes, reindex_search_index


def test_reindex_search_index_returns_consistent_payload(monkeypatch):
    orchestration = MagicMock()
    orchestration.reindex_index.return_value = 5
    monkeypatch.setattr("apps.search.tasks.SearchOrchestrationService", lambda: orchestration)
    monkeypatch.setattr(reindex_search_index, "update_state", lambda *args, **kwargs: None)

    result = reindex_search_index.run("item-parts")

    assert result == {"action": "reindex", "index_type": "item-parts", "indexed": 5}
    orchestration.reindex_index.assert_called_once()


def test_clear_search_index_returns_consistent_payload(monkeypatch):
    orchestration = MagicMock()
    monkeypatch.setattr("apps.search.tasks.SearchOrchestrationService", lambda: orchestration)

    result = clear_search_index.run("item-parts")

    assert result == {"action": "clear", "index_type": "item-parts"}
    orchestration.clear_index.assert_called_once_with("item-parts")


def test_reindex_all_search_indexes_aggregates_counts(monkeypatch):
    orchestration = MagicMock()
    orchestration.reindex_all.return_value = {"item-parts": 2, "scribes": 3}
    monkeypatch.setattr("apps.search.tasks.SearchOrchestrationService", lambda: orchestration)
    monkeypatch.setattr(reindex_all_search_indexes, "update_state", lambda *args, **kwargs: None)

    result = reindex_all_search_indexes.run()

    assert result == {"action": "reindex_all", "indexed": 5}
    orchestration.reindex_all.assert_called_once()

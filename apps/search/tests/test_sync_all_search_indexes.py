from django.core.management.base import CommandError
import pytest

from apps.common.tests.commands import run_command
from apps.search.management.commands import sync_all_search_indexes
from apps.search.types import IndexType


def _reindex_all_returning(monkeypatch, indexed: dict[str, int]) -> None:
    monkeypatch.setattr(sync_all_search_indexes.IndexingService, "reindex_all", lambda self: indexed)


def test_reports_the_total_when_every_index_rebuilt(monkeypatch):
    _reindex_all_returning(monkeypatch, {index_type.segment: 2 for index_type in IndexType})

    out = run_command("sync_all_search_indexes")

    assert f"Done. Total documents indexed: {2 * len(IndexType)}." in out


def test_fails_naming_the_indexes_that_did_not_rebuild(monkeypatch):
    failed = [IndexType.HANDS.segment, IndexType.GRAPHS.segment]
    _reindex_all_returning(
        monkeypatch, {index_type.segment: 2 for index_type in IndexType if index_type.segment not in failed}
    )

    with pytest.raises(CommandError, match=f"Reindex failed for {failed[0]}, {failed[1]};"):
        run_command("sync_all_search_indexes")

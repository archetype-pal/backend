from unittest.mock import MagicMock, call

import pytest

from apps.search.services import SearchOrchestrationService, resolve_index_type_segment
from apps.search.types import IndexType


def test_resolve_index_type_segment_returns_index_type():
    assert resolve_index_type_segment("item-parts") is IndexType.ITEM_PARTS


def test_resolve_index_type_segment_raises_for_unknown():
    with pytest.raises(ValueError, match="Unknown index type"):
        resolve_index_type_segment("unknown")


def test_reindex_all_uses_single_orchestration_path():
    indexing_service = MagicMock()
    indexing_service.reindex.return_value = 3
    service = SearchOrchestrationService(indexing_service=indexing_service)

    result = service.reindex_all()

    expected_segments = {index_type.to_url_segment() for index_type in IndexType}
    assert set(result.keys()) == expected_segments
    assert all(count == 3 for count in result.values())
    assert indexing_service.reindex.call_count == len(IndexType)


def test_clear_and_reindex_all_advances_reporter_per_index():
    """The reporter is informed once per index segment (advance_to) AND for
    each batch the underlying reindex emits (report_batch). The orchestrator
    is responsible only for the outer advance_to; IndexingService owns batch
    reports — verified here by having the mocked reindex echo a batch back."""
    indexing_service = MagicMock()
    indexing_service.reindex.side_effect = lambda _idx, *, reporter=None: (
        (reporter.report_batch(2, 2) if reporter else None) or 2
    )
    service = SearchOrchestrationService(indexing_service=indexing_service)
    reporter = MagicMock()

    service.clear_and_reindex_all(reporter=reporter)

    assert indexing_service.clear.call_count == len(IndexType)
    assert indexing_service.reindex.call_count == len(IndexType)
    # One advance_to per index segment, in source order.
    assert reporter.advance_to.call_count == len(IndexType)
    reporter.advance_to.assert_has_calls(
        [
            call(position, len(IndexType), index_type.to_url_segment())
            for position, index_type in enumerate(IndexType, start=1)
        ],
        any_order=False,
    )
    # Each reindex emitted one batch through the same reporter instance.
    assert reporter.report_batch.call_count == len(IndexType)
    indexing_service.clear.assert_has_calls([call(index_type) for index_type in IndexType], any_order=False)

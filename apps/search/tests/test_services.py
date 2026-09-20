import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call

from meilisearch.errors import MeilisearchApiError
import pytest

from apps.search.services import (
    IndexingService,
    SearchOrchestrationService,
    SearchService,
    resolve_index_type_segment,
)
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult


def _api_error(code: str) -> MeilisearchApiError:
    """A Meilisearch API error carrying *code*, built the way the SDK builds one."""
    response = MagicMock()
    response.status_code = 400
    response.text = json.dumps({"message": f"simulated {code}", "code": code, "type": "invalid_request"})
    return MeilisearchApiError("", response)


class TestSearchService:
    def test_search_returns_reader_result(self):
        mock_reader = MagicMock()
        expected = SearchResult(hits=[{"id": 1, "shelfmark": "MS 1"}], total=1, limit=20, offset=0)
        mock_reader.search.return_value = (expected, None)
        service = SearchService(reader=mock_reader)
        query = SearchQuery(q="test", limit=20, offset=0)
        result = service.search(IndexType.ITEM_PARTS, query)
        assert result == expected
        mock_reader.search.assert_called_once_with(IndexType.ITEM_PARTS, query, facet_attributes=None)

    def test_get_document_returns_reader_result(self):
        mock_reader = MagicMock()
        mock_reader.get_document_by_id.return_value = {"id": 1, "shelfmark": "MS 1"}
        service = SearchService(reader=mock_reader)
        result = service.get_document(IndexType.ITEM_PARTS, 1)
        assert result == {"id": 1, "shelfmark": "MS 1"}
        mock_reader.get_document_by_id.assert_called_once_with(IndexType.ITEM_PARTS, 1)

    def test_get_document_returns_none_when_reader_returns_none(self):
        mock_reader = MagicMock()
        mock_reader.get_document_by_id.return_value = None
        service = SearchService(reader=mock_reader)
        result = service.get_document(IndexType.ITEM_PARTS, 999)
        assert result is None

    def test_get_facets_returns_facet_result(self):
        mock_reader = MagicMock()
        facets = FacetResult(facet_distribution={"type": {"charter": 2}}, facet_stats={})
        mock_reader.search.return_value = (
            SearchResult(hits=[], total=0, limit=20, offset=0),
            facets,
        )
        service = SearchService(reader=mock_reader)
        query = SearchQuery()
        result = service.get_facets(IndexType.ITEM_PARTS, query, ["type"])
        assert result.facet_distribution == {"type": {"charter": 2}}
        mock_reader.search.assert_called_once_with(IndexType.ITEM_PARTS, query, facet_attributes=["type"])

    def test_get_facets_returns_empty_when_reader_returns_none_facets(self):
        mock_reader = MagicMock()
        mock_reader.search.return_value = (
            SearchResult(hits=[], total=0, limit=20, offset=0),
            None,
        )
        service = SearchService(reader=mock_reader)
        result = service.get_facets(IndexType.ITEM_PARTS, SearchQuery(), ["type"])
        assert result.facet_distribution == {}
        assert result.facet_stats == {}

    def test_get_facets_degrades_when_the_live_index_does_not_know_a_facet_yet(self):
        """Deploy-order guard: facets come from registry.py, settings from the index.

        Between deploying a new facet and running `setup-search-indexes`,
        Meilisearch rejects the whole search with `invalid_search_facets`. The
        public search page must still render (hits are fetched separately), so
        the facets degrade to empty instead of raising a 500.
        """
        mock_reader = MagicMock()
        mock_reader.search.side_effect = _api_error("invalid_search_facets")
        service = SearchService(reader=mock_reader)

        result = service.get_facets(IndexType.ITEM_PARTS, SearchQuery(), ["type", "material"])

        assert result.facet_distribution == {}
        assert result.facet_stats == {}

    def test_get_facets_reraises_other_meilisearch_api_errors(self):
        mock_reader = MagicMock()
        mock_reader.search.side_effect = _api_error("index_not_found")
        service = SearchService(reader=mock_reader)

        with pytest.raises(MeilisearchApiError):
            service.get_facets(IndexType.ITEM_PARTS, SearchQuery(), ["type"])

    def test_suggest_attaches_kwic_snippet_for_text_index(self):
        mock_reader = MagicMock()
        hit = {
            "id": 12,
            "shelfmark": "DCD Misc. Ch. 608",
            "_formatted": {"content": "__hl_start__William__hl_end__, king of Scots"},
        }
        mock_reader.multi_search.return_value = [
            (IndexType.TEXTS, SearchResult(hits=[hit], total=1, limit=5, offset=0))
        ]
        service = SearchService(reader=mock_reader)

        result = service.suggest([IndexType.TEXTS], "william", per_type_limit=5)

        assert result["texts"][0]["label"] == "DCD Misc. Ch. 608"
        assert result["texts"][0]["snippet"] == "__hl_start__William__hl_end__, king of Scots"
        # The text query must request a cropped, retrievable `content`.
        specs = mock_reader.multi_search.call_args.args[0]
        index_type, query = specs[0]
        assert index_type is IndexType.TEXTS
        assert query.attributes_to_crop == ["content"]
        assert "content" in query.attributes_to_retrieve

    def test_suggest_omits_snippet_when_match_not_in_content(self):
        mock_reader = MagicMock()
        # A shelfmark-only match crops from the start, with no highlight markers.
        hit = {"id": 12, "shelfmark": "DCD Misc. Ch. 608", "_formatted": {"content": "In nomine domini"}}
        mock_reader.multi_search.return_value = [
            (IndexType.TEXTS, SearchResult(hits=[hit], total=1, limit=5, offset=0))
        ]
        service = SearchService(reader=mock_reader)

        result = service.suggest([IndexType.TEXTS], "dcd", per_type_limit=5)

        assert "snippet" not in result["texts"][0]

    def test_suggest_does_not_crop_non_text_index(self):
        mock_reader = MagicMock()
        mock_reader.multi_search.return_value = [
            (IndexType.SCRIBES, SearchResult(hits=[{"id": 7, "name": "William, scribe"}], total=1, limit=5, offset=0))
        ]
        service = SearchService(reader=mock_reader)

        result = service.suggest([IndexType.SCRIBES], "william", per_type_limit=5)

        assert result["scribes"][0] == {"id": "7", "label": "William, scribe"}
        specs = mock_reader.multi_search.call_args.args[0]
        assert specs[0][1].attributes_to_crop == []


class _FakeQuerySet:
    def __init__(self, items):
        self._items = list(items)

    def count(self):
        return len(self._items)

    def iterator(self, chunk_size=500):
        del chunk_size
        yield from self._items


def _stub_index_source(monkeypatch, builder, items):
    registration = SimpleNamespace(builder=builder)
    monkeypatch.setattr(
        "apps.search.services.get_registration",
        lambda index_type: registration if index_type == IndexType.ITEM_PARTS else None,
    )
    monkeypatch.setattr(
        "apps.search.services.get_queryset_for_index",
        lambda index_type: _FakeQuerySet(items),
    )


class TestIndexingService:
    def test_reindex_builds_into_staging_and_swaps_it_in(self, monkeypatch, db):
        del db
        writer = MagicMock()
        _stub_index_source(
            monkeypatch,
            builder=lambda obj: ({"id": obj["id"]}, {"id": obj["id"] + 100}),
            items=[{"id": 1}, {"id": 2}],
        )

        processed = IndexingService(writer=writer).reindex(IndexType.ITEM_PARTS)

        assert processed == 2
        writer.ensure_index_and_settings.assert_called_once_with(IndexType.ITEM_PARTS)
        writer.prepare_build_index.assert_called_once_with(IndexType.ITEM_PARTS)
        writer.add_documents_to_build.assert_called_once_with(
            IndexType.ITEM_PARTS,
            [{"id": 1}, {"id": 101}, {"id": 2}, {"id": 102}],
        )
        writer.swap_with_build.assert_called_once_with(IndexType.ITEM_PARTS)
        writer.drop_build_index.assert_called_once_with(IndexType.ITEM_PARTS)
        writer.delete_all.assert_not_called()

    def test_reindex_swaps_only_after_every_batch_is_written(self, monkeypatch, db):
        # Swapping mid-run would serve a partially built index.
        del db
        call_order: list[str] = []
        writer = MagicMock()
        writer.add_documents_to_build.side_effect = lambda *_a, **_kw: call_order.append("write")
        writer.swap_with_build.side_effect = lambda *_a, **_kw: call_order.append("swap")
        _stub_index_source(
            monkeypatch,
            builder=lambda obj: ({"id": obj["id"]},),
            items=[{"id": 1}, {"id": 2}, {"id": 3}],
        )

        IndexingService(writer=writer).reindex(IndexType.ITEM_PARTS)

        assert call_order.index("swap") == len(call_order) - 1, call_order


class TestResolveIndexTypeSegment:
    def test_resolves_a_known_segment(self):
        assert resolve_index_type_segment("item-parts") is IndexType.ITEM_PARTS

    def test_raises_for_an_unknown_segment(self):
        with pytest.raises(ValueError, match="Unknown index type"):
            resolve_index_type_segment("unknown")


class TestSearchOrchestrationService:
    def test_reindex_all_covers_every_index(self):
        indexing_service = MagicMock()
        indexing_service.reindex.return_value = 3

        result = SearchOrchestrationService(indexing_service=indexing_service).reindex_all()

        assert set(result) == {index_type.to_url_segment() for index_type in IndexType}
        assert all(count == 3 for count in result.values())
        assert indexing_service.reindex.call_count == len(IndexType)

    def test_clear_and_reindex_all_advances_the_reporter_per_index(self):
        # The orchestrator owns only the outer advance_to; IndexingService emits
        # the batch reports, mocked here to echo one back per index.
        indexing_service = MagicMock()
        indexing_service.reindex.side_effect = lambda _idx, *, reporter=None: (
            (reporter.report_batch(2, 2) if reporter else None) or 2
        )
        reporter = MagicMock()

        SearchOrchestrationService(indexing_service=indexing_service).clear_and_reindex_all(reporter=reporter)

        assert indexing_service.clear.call_count == 0
        assert indexing_service.reindex.call_count == len(IndexType)
        reporter.advance_to.assert_has_calls(
            [
                call(position, len(IndexType), index_type.to_url_segment())
                for position, index_type in enumerate(IndexType, start=1)
            ],
            any_order=False,
        )
        assert reporter.report_batch.call_count == len(IndexType)
        indexing_service.reindex.assert_has_calls(
            [call(index_type, reporter=reporter) for index_type in IndexType], any_order=False
        )

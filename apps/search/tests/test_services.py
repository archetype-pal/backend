import json
from unittest.mock import MagicMock, call

from meilisearch.errors import MeilisearchApiError
import pytest

from apps.manuscripts.tests.factories import ItemPartFactory
from apps.search.services import IndexingService, SearchService
from apps.search.types import IndexType, SearchQuery, SearchResult


def _api_error(code: str) -> MeilisearchApiError:
    """A Meilisearch API error carrying *code*, built the way the SDK builds one."""
    response = MagicMock()
    response.status_code = 400
    response.text = json.dumps({"message": f"simulated {code}", "code": code, "type": "invalid_request"})
    return MeilisearchApiError("", response)


class TestSearchService:
    def test_search_with_facets_degrades_when_the_live_index_does_not_know_a_facet_yet(self):
        """Deploy-order guard: facets come from registry.py, settings from the index.

        Between deploying a new facet and running `setup-search-indexes`,
        Meilisearch rejects the whole search with `invalid_search_facets`. The
        public search page must still render, so the service retries without
        facets and reports none instead of raising a 500.
        """
        mock_reader = MagicMock()
        hits = SearchResult(hits=[{"id": 1}], total=1, limit=20, offset=0)
        mock_reader.search.side_effect = [_api_error("invalid_search_facets"), (hits, None)]
        service = SearchService(reader=mock_reader)

        result, facet_result = service.search_with_facets(IndexType.ITEM_PARTS, SearchQuery(), ["type", "material"])

        assert result == hits
        assert facet_result.facet_distribution == {}
        assert mock_reader.search.call_args_list[-1].kwargs == {"facet_attributes": None}

    def test_search_with_facets_reraises_other_meilisearch_api_errors(self):
        mock_reader = MagicMock()
        mock_reader.search.side_effect = _api_error("index_not_found")
        service = SearchService(reader=mock_reader)

        with pytest.raises(MeilisearchApiError):
            service.search_with_facets(IndexType.ITEM_PARTS, SearchQuery(), ["type"])

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


@pytest.mark.django_db
class TestIndexingService:
    def test_reindex_builds_into_staging_and_swaps_it_in_after_every_batch(self):
        parts = ItemPartFactory.create_batch(3)
        call_order: list[str] = []
        writer = MagicMock()
        writer.add_documents_to_build.side_effect = lambda *_a, **_kw: call_order.append("write")
        writer.swap_with_build.side_effect = lambda *_a, **_kw: call_order.append("swap")

        processed = IndexingService(writer=writer).reindex(IndexType.ITEM_PARTS)

        assert processed == 3
        writer.ensure_index_and_settings.assert_called_once_with(IndexType.ITEM_PARTS)
        writer.prepare_build_index.assert_called_once_with(IndexType.ITEM_PARTS)
        (index_type, documents), _ = writer.add_documents_to_build.call_args
        assert index_type is IndexType.ITEM_PARTS
        assert [doc["id"] for doc in documents] == [part.pk for part in parts]
        # Swapping mid-run would serve a partially built index; clearing first would serve none.
        assert call_order == ["write", "swap"]
        writer.drop_build_index.assert_called_once_with(IndexType.ITEM_PARTS)
        writer.delete_all.assert_not_called()


class TestReindexAll:
    def test_reindex_all_covers_every_index_and_advances_the_reporter(self, monkeypatch):
        # reindex_all owns only the outer advance_to; `reindex` emits the batch
        # reports, stubbed here to echo one back per index.
        service = IndexingService(writer=MagicMock())
        seen: list = []

        def fake_reindex(index_type, *, reporter=None):
            seen.append(index_type)
            reporter.report_batch(2, 2)
            return 2

        monkeypatch.setattr(service, "reindex", fake_reindex)
        reporter = MagicMock()

        result = service.reindex_all(reporter=reporter)

        assert seen == list(IndexType)
        assert result == {index_type.segment: 2 for index_type in IndexType}
        reporter.advance_to.assert_has_calls(
            [call(position, len(IndexType), index_type.segment) for position, index_type in enumerate(IndexType, 1)],
            any_order=False,
        )
        assert reporter.report_batch.call_count == len(IndexType)

from unittest.mock import MagicMock

import pytest

from apps.search.registry import get_queryset_for_index
from apps.search.services import SearchService
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult


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


@pytest.mark.django_db
class TestGetQuerysetForIndex:
    def test_item_parts_returns_item_part_queryset(self):
        from apps.manuscripts.models import ItemPart

        qs = get_queryset_for_index(IndexType.ITEM_PARTS)
        assert qs.model is ItemPart
        assert qs.ordered

    def test_scribes_returns_scribe_queryset(self):
        from apps.scribes.models import Scribe

        qs = get_queryset_for_index(IndexType.SCRIBES)
        assert qs.model is Scribe

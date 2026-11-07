import pytest

from apps.search.registry import get_registration
from apps.search.types import FilterSpec, IndexType, SearchQuery, SortSpec


class TestMultiSearch:
    def test_multi_search_builds_one_request_and_maps_results_in_spec_order(self, mock_reader):
        reader = mock_reader
        reader._client.multi_search.return_value = {
            "results": [
                {"hits": [{"id": 1}], "estimatedTotalHits": 1, "limit": 5, "offset": 0},
                {"hits": [{"id": 2}], "estimatedTotalHits": 3, "limit": 5, "offset": 0},
            ]
        }
        specs = [
            (IndexType.TEXTS, SearchQuery(q="william", limit=5)),
            (IndexType.SCRIBES, SearchQuery(q="william", limit=5)),
        ]

        out = reader.multi_search(specs)

        assert [index_type for index_type, _ in out] == [IndexType.TEXTS, IndexType.SCRIBES]
        assert out[0][1].hits == [{"id": 1}]
        assert out[1][1].hits == [{"id": 2}]
        assert out[1][1].total == 3
        reader._client.multi_search.assert_called_once()
        queries = reader._client.multi_search.call_args.args[0]
        assert len(queries) == 2
        assert queries[0]["indexUid"].endswith("texts")
        assert queries[0]["q"] == "william"
        assert queries[0]["attributesToHighlight"] == get_registration(IndexType.TEXTS).searchable_attributes

    def test_formatted_is_pruned_to_the_highlighted_attributes(self, mock_reader):
        reader = mock_reader
        hit = {
            "id": 1,
            "content": "the whole transcription",
            "coordinates": "{}",
            "_formatted": {"id": "1", "content": "the __hl_start__whole__hl_end__ …", "coordinates": "{}"},
        }
        reader._client.index.return_value.search.return_value = {"hits": [hit], "estimatedTotalHits": 1}

        result, _ = reader.search(IndexType.TEXTS, SearchQuery(q="whole", attributes_to_crop=["content"]))

        assert result.hits[0]["coordinates"] == "{}"  # the raw attribute is untouched
        assert result.hits[0]["_formatted"] == {"content": "the __hl_start__whole__hl_end__ …"}
        options = reader._client.index.return_value.search.call_args.args[1]
        assert options["attributesToCrop"] == ["content"]

    def test_a_sort_on_shelfmark_reaches_meilisearch_as_its_natural_order_alias(self, mock_reader):
        reader = mock_reader
        reader._client.index.return_value.search.return_value = {"hits": []}

        reader.search(IndexType.ITEM_PARTS, SearchQuery(sort_spec=SortSpec("shelfmark", ascending=False)))

        options = reader._client.index.return_value.search.call_args.args[1]
        assert options["sort"] == ["shelfmark_sort:desc"]

    def test_multi_search_empty_specs_short_circuits(self, mock_reader):
        reader = mock_reader

        assert reader.multi_search([]) == []
        reader._client.multi_search.assert_not_called()


class TestApplyIndexSettings:
    def test_settings_pushed_to_the_index(self, mock_writer):
        writer = mock_writer
        index = writer._client.index.return_value

        writer._apply_index_settings("texts", IndexType.TEXTS)

        index.update_typo_tolerance.assert_called_once_with({"disableOnNumbers": True})
        index.update_searchable_attributes.assert_called_once()
        index.update_filterable_attributes.assert_called_once()
        index.update_pagination_settings.assert_called_once()
        # Sorting works on the public attributes and their natural-order aliases.
        sortable = index.update_sortable_attributes.call_args.args[0]
        assert "shelfmark" in sortable
        assert "shelfmark_sort" in sortable


class TestSimilar:
    def test_asks_for_the_documents_nearest_by_the_index_s_embedder(self, mock_reader):
        reader = mock_reader
        reader._client.index.return_value.get_similar_documents.return_value = {
            "hits": [{"id": 8, "_rankingScore": 0.9}],
            "estimatedTotalHits": 40,
            "limit": 5,
            "offset": 10,
        }
        query = SearchQuery(
            limit=5,
            offset=10,
            filter_spec=FilterSpec(not_equal={"shelfmark": "Ch. 1"}),
            attributes_to_retrieve=["id", "allograph"],
        )

        result = reader.similar(IndexType.GRAPHS, 7, query)

        reader._client.index.return_value.get_similar_documents.assert_called_once_with(
            {
                "id": "7",
                "embedder": "glyph",
                "limit": 5,
                "offset": 10,
                "showRankingScore": True,
                "filter": 'has_glyph_vector = true AND (shelfmark != "Ch. 1")',
                "attributesToRetrieve": ["id", "allograph"],
            }
        )
        assert (result.hits, result.total, result.limit, result.offset) == (
            [{"id": 8, "_rankingScore": 0.9}],
            40,
            5,
            10,
        )

    def test_counts_only_documents_with_a_vector_and_asks_for_no_fields_it_was_not_given(self, mock_reader):
        """Meilisearch counts every document the filter lets through, but returns only those with a vector."""
        mock_reader._client.index.return_value.get_similar_documents.return_value = {"hits": []}

        mock_reader.similar(IndexType.GRAPHS, 7, SearchQuery())

        params = mock_reader._client.index.return_value.get_similar_documents.call_args.args[0]
        assert params["filter"] == "has_glyph_vector = true"
        assert "attributesToRetrieve" not in params

    def test_an_index_without_vectors_is_refused_before_meilisearch_is_asked(self, mock_reader):
        with pytest.raises(ValueError, match="no vectors"):
            mock_reader.similar(IndexType.TEXTS, 7, SearchQuery())

        mock_reader._client.index.assert_not_called()

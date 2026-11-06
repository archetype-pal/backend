from apps.search.registry import get_registration
from apps.search.types import IndexType, SearchQuery, SortSpec


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

from unittest.mock import MagicMock

from apps.search.meilisearch.reader import MeilisearchIndexReader
from apps.search.types import IndexType, SearchQuery


class TestMultiSearch:
    def test_multi_search_builds_one_request_and_maps_results_in_spec_order(self):
        reader = MeilisearchIndexReader()
        reader._client = MagicMock()
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
        # A single federated round-trip carrying one query per index.
        reader._client.multi_search.assert_called_once()
        queries = reader._client.multi_search.call_args.args[0]
        assert len(queries) == 2
        assert queries[0]["indexUid"].endswith("texts")
        assert queries[0]["q"] == "william"
        assert queries[0]["attributesToHighlight"] == ["*"]

    def test_multi_search_empty_specs_short_circuits(self):
        reader = MeilisearchIndexReader()
        reader._client = MagicMock()

        assert reader.multi_search([]) == []
        reader._client.multi_search.assert_not_called()

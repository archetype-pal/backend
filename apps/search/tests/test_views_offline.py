"""The public search endpoints, exercised against an in-memory backend.

`test_search_api.py` is the smoke test against a live Meilisearch; this covers
the view layer's own logic — paging links, ordering options, the facets degrade
path, export formats and scopes, suggestion limits — without one.
"""

import json

from meilisearch.errors import MeilisearchApiError
import pytest

from apps.search.services import SearchService
from apps.search.types import FacetResult, IndexType, SearchQuery, SearchResult


class FakeBackend:
    """Implements `SearchBackend` over a list of documents; records every query it answers."""

    def __init__(self, documents: list[dict], *, facets_error: bool = False):
        self.documents = documents
        self.queries: list[SearchQuery] = []
        self.facets_error = facets_error

    def search(self, index_type, query, *, facet_attributes=None):
        self.queries.append(query)
        if facet_attributes and self.facets_error:
            response = type("R", (), {"status_code": 400, "text": json.dumps({"code": "invalid_search_facets"})})()
            raise MeilisearchApiError("", response)
        page = self.documents[query.offset : query.offset + query.limit]
        result = SearchResult(hits=page, total=len(self.documents), limit=query.limit, offset=query.offset)
        facets = FacetResult(facet_distribution={"type": {"charter": len(self.documents)}})
        return result, (facets if facet_attributes else None)

    def multi_search(self, specs):
        return [(index_type, self.search(index_type, query)[0]) for index_type, query in specs]

    def get_document_by_id(self, index_type, doc_id):
        return next((d for d in self.documents if str(d["id"]) == str(doc_id)), None)


@pytest.fixture
def backend(monkeypatch):
    docs = [
        {"id": i, "display_label": f"MS {i}", "repository_name": "BL", "shelfmark": f"Add {i}", "date": "1100"}
        for i in range(1, 8)
    ]
    fake = FakeBackend(docs)
    monkeypatch.setattr("apps.search.views_search.SearchService", lambda: SearchService(reader=fake))
    return fake


class TestList:
    def test_pages_results(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/", {"limit": 2, "offset": 2})
        assert response.status_code == 200
        assert [hit["id"] for hit in response.data["results"]] == [3, 4]
        assert response.data["total"] == 7

    def test_unknown_index_is_404(self, api_client, backend):
        assert api_client.get("/api/v1/search/nope/").status_code == 404

    def test_retrieve(self, api_client, backend):
        assert api_client.get("/api/v1/search/item-parts/3/").data["shelfmark"] == "Add 3"
        assert api_client.get("/api/v1/search/item-parts/99/").status_code == 404


class TestFacets:
    def test_one_backend_call_returns_hits_and_facets(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/facets/", {"limit": 3})
        assert response.status_code == 200
        assert response.data["facetDistribution"] == {"type": {"charter": 7}}
        assert len(response.data["results"]) == 3
        assert len(backend.queries) == 1

    def test_paging_links_keep_the_query_and_move_the_offset(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/facets/", {"limit": 3, "offset": 3, "q": "x"})
        assert "offset=6" in response.data["next"] and "q=x" in response.data["next"]
        assert "offset=0" in response.data["previous"]
        last = api_client.get("/api/v1/search/item-parts/facets/", {"limit": 3, "offset": 6})
        assert last.data["next"] is None

    def test_ordering_options_cover_every_sortable_attribute_both_ways(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/facets/", {"ordering": "-shelfmark"})
        ordering = response.data["ordering"]
        assert ordering["current"] == "-shelfmark"
        names = {option["name"] for option in ordering["options"]}
        assert {"shelfmark", "-shelfmark", "date_min", "-date_min"} <= names
        assert all("offset=0" in option["url"] for option in ordering["options"])

    def test_degrades_to_no_facets_when_the_index_settings_are_stale(self, api_client, monkeypatch):
        fake = FakeBackend([{"id": 1}], facets_error=True)
        monkeypatch.setattr("apps.search.views_search.SearchService", lambda: SearchService(reader=fake))
        response = api_client.get("/api/v1/search/item-parts/facets/")
        assert response.status_code == 200
        assert response.data["facetDistribution"] == {}
        assert response.data["results"] == [{"id": 1}]


class TestExport:
    def test_csv_is_the_default_and_only_covers_the_page(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"limit": 2})
        lines = response.data["content"].strip().splitlines()
        assert lines[0] == "id,display_label,repository_name,shelfmark,date"
        assert len(lines) == 3

    def test_scope_all_pages_through_the_backend(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"export_format": "json", "scope": "all"})
        assert response.data["count"] == 7
        assert [q.limit for q in backend.queries] == [200]

    def test_bibtex_only_for_citable_indexes(self, api_client, backend):
        ok = api_client.get("/api/v1/search/item-parts/export/", {"export_format": "bibtex"})
        assert ok.status_code == 200 and ok.data["content"].startswith("@misc{BL_Add_1_1100,")
        denied = api_client.get("/api/v1/search/graphs/export/", {"export_format": "bibtex"})
        assert denied.status_code == 400

    def test_unknown_format_is_400(self, api_client, backend):
        assert api_client.get("/api/v1/search/item-parts/export/", {"export_format": "xlsx"}).status_code == 400

    @pytest.mark.parametrize(
        ("export_format", "content_type", "filename"),
        [
            ("csv", "text/csv; charset=utf-8", "item-parts-page.csv"),
            ("bibtex", "application/x-bibtex; charset=utf-8", "item-parts-page.bib"),
            ("json", "application/json", "item-parts-page.json"),
        ],
    )
    def test_download_serves_the_file_itself(self, api_client, backend, export_format, content_type, filename):
        response = api_client.get(
            "/api/v1/search/item-parts/export/", {"export_format": export_format, "download": "1", "limit": 2}
        )
        assert response.status_code == 200
        assert response["Content-Type"] == content_type
        assert response["Content-Disposition"] == f'attachment; filename="{filename}"'
        body = response.content.decode()
        assert "Add 1" in body and "Add 3" not in body  # the page, not the whole index

    def test_download_scope_all_names_the_scope(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"download": "true", "scope": "all"})
        assert response["Content-Disposition"] == 'attachment; filename="item-parts-all.csv"'
        assert len(response.content.decode().strip().splitlines()) == 8

    def test_download_off_keeps_the_json_wrapper(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"download": "0"})
        assert response["Content-Type"] == "application/json"
        assert "content" in response.data


class TestSuggest:
    def test_short_queries_return_nothing(self, api_client, backend):
        assert api_client.get("/api/v1/search/suggest/", {"q": "a"}).data["suggestions"] == {}

    def test_limits_types_and_per_type_count(self, api_client, backend):
        response = api_client.get("/api/v1/search/suggest/", {"q": "ms", "types": "item-parts,bogus", "limit": 50})
        assert list(response.data["suggestions"]) == ["item-parts"]
        assert len(response.data["suggestions"]["item-parts"]) == 7  # corpus is smaller than the clamp (10)
        assert backend.queries[0].limit == 10

    def test_defaults_to_every_index(self, api_client, backend):
        response = api_client.get("/api/v1/search/suggest/", {"q": "ms"})
        assert set(response.data["suggestions"]) == {index_type.segment for index_type in IndexType}

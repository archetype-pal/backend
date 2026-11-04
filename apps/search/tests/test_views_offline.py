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
        self.similar_error: Exception | None = None

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

    def similar(self, index_type, document_id, query):
        """The other documents, nearest first by their place in the list."""
        self.queries.append(query)
        if self.similar_error:
            raise self.similar_error
        others = [{**d, "_rankingScore": 0.9} for d in self.documents if str(d["id"]) != str(document_id)]
        page = others[query.offset : query.offset + query.limit]
        return SearchResult(hits=page, total=len(others), limit=query.limit, offset=query.offset)


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


class TestSimilar:
    @pytest.fixture
    def glyphs(self, monkeypatch):
        docs = [{"id": i, "allograph": "a", "shelfmark": f"Ch. {i}", "has_glyph_vector": i != 4} for i in range(1, 6)]
        fake = FakeBackend(docs)
        monkeypatch.setattr("apps.search.views_search.SearchService", lambda: SearchService(reader=fake))
        return fake

    def test_pages_the_glyphs_nearest_this_one_with_their_scores(self, api_client, glyphs):
        response = api_client.get(
            "/api/v1/search/graphs/2/similar/", {"limit": 2, "offset": 1, "shelfmark__not": "Ch. 9"}
        )

        assert response.status_code == 200
        assert [hit["id"] for hit in response.data["results"]] == [3, 4]
        assert response.data["results"][0]["_rankingScore"] == 0.9
        assert (response.data["total"], response.data["limit"], response.data["offset"]) == (4, 2, 1)
        assert glyphs.queries[-1].filter_spec.not_equal == {"shelfmark": "Ch. 9"}

    @pytest.mark.parametrize(
        "url",
        [
            "/api/v1/search/graphs/99/similar/",
            "/api/v1/search/graphs/4/similar/",
            "/api/v1/search/texts/1/similar/",
            "/api/v1/search/nope/1/similar/",
        ],
    )
    def test_there_is_nothing_to_search_from(self, api_client, glyphs, url):
        response = api_client.get(url)

        assert response.status_code == 404
        assert response.data["detail"]

    def test_an_index_not_yet_given_its_embedder_is_unavailable(self, api_client, glyphs):
        response = type("R", (), {"status_code": 400, "text": json.dumps({"code": "invalid_similar_embedder"})})()
        glyphs.similar_error = MeilisearchApiError("", response)

        response = api_client.get("/api/v1/search/graphs/2/similar/")

        assert response.status_code == 503
        assert "reindex" in response.data["detail"]


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
        lines = response.content.decode().strip().splitlines()
        assert lines[0] == "id,display_label,repository_name,shelfmark,date"
        assert len(lines) == 3

    def test_scope_all_pages_through_the_backend(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"export_format": "json", "scope": "all"})
        assert len(json.loads(response.content)) == 7
        assert [q.limit for q in backend.queries] == [200]

    def test_bibtex_only_for_citable_indexes(self, api_client, backend):
        ok = api_client.get("/api/v1/search/item-parts/export/", {"export_format": "bibtex"})
        assert ok.status_code == 200 and ok.content.decode().startswith("@misc{BL_Add_1_1100,")
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
    def test_serves_the_file_itself(self, api_client, backend, export_format, content_type, filename):
        response = api_client.get("/api/v1/search/item-parts/export/", {"export_format": export_format, "limit": 2})
        assert response.status_code == 200
        assert response["Content-Type"] == content_type
        assert response["Content-Disposition"] == f'attachment; filename="{filename}"'
        body = response.content.decode()
        assert "Add 1" in body and "Add 3" not in body  # the page, not the whole index

    def test_scope_all_names_the_scope(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"scope": "all"})
        assert response["Content-Disposition"] == 'attachment; filename="item-parts-all.csv"'
        assert len(response.content.decode().strip().splitlines()) == 8

    def test_download_flag_no_longer_switches_to_a_json_wrapper(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/export/", {"download": "0"})
        assert response["Content-Type"] == "text/csv; charset=utf-8"
        assert response["Content-Disposition"] == 'attachment; filename="item-parts-page.csv"'


class TestMeta:
    def test_describes_the_index_contract(self, api_client, backend):
        response = api_client.get("/api/v1/search/item-parts/meta/")
        assert response.status_code == 200
        assert response.data["index_type"] == "item-parts"
        assert "shelfmark" in response.data["searchable_attributes"]
        assert "type" in response.data["filterable_attributes"]
        assert "type" in response.data["default_facet_attributes"]
        assert response.data["export_formats"] == ["csv", "json", "bibtex"]
        assert len(backend.queries) == 0  # a contract lookup never searches

    def test_sortable_attributes_are_the_public_names(self, api_client, backend):
        # `shelfmark` sorts through the `shelfmark_sort` alias; the alias stays the reader's business.
        sortable = api_client.get("/api/v1/search/item-parts/meta/").data["sortable_attributes"]
        assert "shelfmark" in sortable
        assert "shelfmark_sort" not in sortable

    def test_bibtex_only_listed_for_citable_indexes(self, api_client, backend):
        assert api_client.get("/api/v1/search/graphs/meta/").data["export_formats"] == ["csv", "json"]

    def test_unknown_index_is_404(self, api_client, backend):
        assert api_client.get("/api/v1/search/nope/meta/").status_code == 404


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

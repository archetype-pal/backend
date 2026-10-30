"""Transport-only DRF viewset for public search endpoints."""

from typing import Any
from urllib.parse import urlencode

from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.common.exports import to_csv
from apps.search.exports import BIBTEX_INDEXES, collect_export_rows, csv_fieldnames, to_bibtex
from apps.search.parsers import parse_facet_attributes, parse_search_query
from apps.search.registry import get_registration
from apps.search.services import SearchService
from apps.search.types import IndexType, SearchResult

_TRUE = {"1", "true", "yes"}


def _page_result(result: SearchResult) -> dict[str, Any]:
    return {"results": result.hits, "total": result.total, "limit": result.limit, "offset": result.offset}


def _attachment(content: str | bytes, content_type: str, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class SearchViewSet(ViewSet):
    def _index_type(self) -> IndexType:
        try:
            return IndexType.from_segment(self.kwargs.get("index_type") or "")
        except ValueError:
            raise NotFound("Invalid index type.") from None

    def _url_with(self, request: Request, **params: str) -> str:
        """The current URL with some query parameters replaced (paging and ordering links)."""
        query = {**dict(request.query_params), **params}
        return f"{request.build_absolute_uri(request.path)}?{urlencode(query, doseq=True)}"

    def list(self, request: Request, index_type: str | None = None) -> Response:
        index = self._index_type()
        result = SearchService().search(index, parse_search_query(request.query_params, index))
        return Response(_page_result(result))

    def retrieve(self, request: Request, pk: str | None = None, index_type: str | None = None) -> Response:
        if pk is None:
            raise NotFound()
        doc = SearchService().get_document(self._index_type(), pk)
        if doc is None:
            raise NotFound()
        return Response(doc)

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request: Request, index_type: str | None = None) -> Response:
        index = self._index_type()
        query = parse_search_query(request.query_params, index)
        facet_attributes = parse_facet_attributes(request.query_params, index)
        result, facets = SearchService().search_with_facets(index, query, facet_attributes)

        sortable = get_registration(index).sortable_attributes
        ordering_options = [
            {
                "name": name,
                "text": f"{attr} ({'asc' if asc else 'desc'})",
                "url": self._url_with(request, ordering=name, offset="0"),
            }
            for attr in sortable
            for asc, name in ((True, attr), (False, f"-{attr}"))
        ]
        current_ordering = (
            f"{'' if query.sort_spec.ascending else '-'}{query.sort_spec.attribute}"
            if query.sort_spec
            else (f"-{sortable[0]}" if sortable else "")
        )
        after, before = result.offset + result.limit, max(0, result.offset - result.limit)
        return Response(
            {
                "facetDistribution": facets.facet_distribution,
                "facetStats": facets.facet_stats,
                **_page_result(result),
                "next": self._url_with(request, offset=str(after)) if after < result.total else None,
                "previous": self._url_with(request, offset=str(before)) if result.offset > 0 else None,
                "ordering": {"current": current_ordering, "options": ordering_options} if sortable else None,
            }
        )

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Request, index_type: str | None = None) -> Response:
        index = self._index_type()
        raw_format = request.query_params.get("export_format") or request.query_params.get("format")
        format_name = (raw_format or "csv").strip().lower()
        scope = (request.query_params.get("scope") or "page").strip().lower()
        query = parse_search_query(request.query_params, index, max_limit=200)
        rows = collect_export_rows(SearchService(), index, query, scope=scope)

        # `download=1` serves the file itself, as the image-text export does; without it
        # the text comes wrapped in JSON, which is what the frontend reads today.
        download = (request.query_params.get("download") or "").strip().lower() in _TRUE

        if format_name == "json":
            if download:
                return _attachment(JSONRenderer().render(rows), "application/json", f"{index.segment}-{scope}.json")
            return Response({"results": rows, "count": len(rows)})
        if format_name == "bibtex":
            if index not in BIBTEX_INDEXES:
                return Response(
                    {"detail": "BibTeX export is supported for manuscripts, scribes, and hands."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            content = to_bibtex(rows, index)
            if download:
                return _attachment(content, "application/x-bibtex; charset=utf-8", f"{index.segment}-{scope}.bib")
            return Response({"content": content})
        if format_name != "csv":
            return Response({"detail": "Unsupported export format."}, status=status.HTTP_400_BAD_REQUEST)
        content = to_csv(rows, csv_fieldnames(rows))
        if download:
            return _attachment(content, "text/csv; charset=utf-8", f"{index.segment}-{scope}.csv")
        return Response({"content": content})


class SearchSuggestViewSet(ViewSet):
    def list(self, request: Request) -> Response:
        query_text = (request.query_params.get("q") or "").strip()
        if len(query_text) < 2:
            return Response({"query": query_text, "suggestions": {}})

        requested = [part.strip() for part in (request.query_params.get("types") or "").split(",") if part.strip()]
        known = [IndexType.from_segment(t) for t in requested if t.replace("-", "_") in IndexType]
        index_types = known or list(IndexType)
        try:
            requested_limit = int(request.query_params.get("limit") or 5)
        except (TypeError, ValueError):  # fmt: skip
            requested_limit = 5
        per_type_limit = min(max(requested_limit, 1), 10)
        suggestions = SearchService().suggest(index_types, query_text, per_type_limit=per_type_limit)
        return Response({"query": query_text, "suggestions": suggestions})

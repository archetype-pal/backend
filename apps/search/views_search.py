"""Transport-only DRF viewset for public search endpoints."""

import csv
import io
from typing import Any
from urllib.parse import urlencode

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.search.index_metadata import SORTABLE_ATTRIBUTES
from apps.search.parsers import parse_facet_attributes, parse_search_query
from apps.search.registry import URL_SEGMENT_TO_INDEX_TYPE
from apps.search.serializers import FacetResultSerializer, SearchResultSerializer
from apps.search.services import SearchService, resolve_index_type_segment
from apps.search.types import IndexType, SearchQuery


class SearchViewSet(ViewSet):
    """Search API: list, retrieve, facets."""

    def _get_index_type(self) -> IndexType | None:
        index_type_slug: str | None = self.kwargs.get("index_type")
        if not index_type_slug:
            return None
        try:
            return resolve_index_type_segment(index_type_slug)
        except ValueError:
            return None

    def list(self, request: Request, index_type: str | None = None) -> Response:
        index: IndexType | None = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        search_query: SearchQuery = parse_search_query(request.query_params, index)
        service: SearchService = SearchService()
        result = service.search(index, search_query)
        serializer = SearchResultSerializer(
            {
                "results": result.hits,
                "total": result.total,
                "limit": result.limit,
                "offset": result.offset,
            }
        )
        return Response(serializer.data)

    def retrieve(self, request: Request, pk: str | None = None, index_type: str | None = None) -> Response:
        index: IndexType | None = self._get_index_type()
        if index is None or pk is None:
            return Response({"detail": "Invalid index type or id."}, status=status.HTTP_404_NOT_FOUND)
        service: SearchService = SearchService()
        doc: dict[str, Any] | None = service.get_document(index, pk)
        if doc is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(doc)

    def _build_ordering(
        self, request: Request, index_type: IndexType, current_sort: str | None
    ) -> dict[str, Any] | None:
        allowed: list[str] = list(SORTABLE_ATTRIBUTES.get(index_type, []))
        if not allowed:
            return None
        base_path: str = request.build_absolute_uri(request.path)
        options: list[dict[str, str]] = []
        for attr in allowed:
            for asc, suffix in [(True, ""), (False, "-")]:
                order_val: str = f"{suffix}{attr}"
                params: dict[str, Any] = dict(request.query_params)
                params["ordering"] = order_val
                params["offset"] = "0"
                url: str = f"{base_path}?{urlencode(params, doseq=True)}"
                text: str = f"{attr} ({'asc' if asc else 'desc'})"
                options.append({"name": order_val, "text": text, "url": url})
        return {
            "current": current_sort or (f"-{allowed[0]}" if allowed else ""),
            "options": options,
        }

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request: Request, index_type: str | None = None) -> Response:
        index: IndexType | None = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        search_query: SearchQuery = parse_search_query(request.query_params, index)
        facet_attributes: list[str] = parse_facet_attributes(request.query_params, index)
        service: SearchService = SearchService()
        search_result = service.search(index, search_query)
        facet_result = service.get_facets(index, search_query, facet_attributes)

        total: int = search_result.total
        limit: int = search_result.limit
        offset: int = search_result.offset
        base_url: str = request.build_absolute_uri(request.path)
        params: dict[str, Any] = dict(request.query_params)

        next_url: str | None = None
        if offset + limit < total:
            params["offset"] = str(offset + limit)
            next_url = f"{base_url}?{urlencode(params, doseq=True)}"
        prev_url: str | None = None
        if offset > 0:
            new_offset: int = max(0, offset - limit)
            params["offset"] = str(new_offset)
            prev_url = f"{base_url}?{urlencode(params, doseq=True)}"

        current_ordering: str | None = (
            f"{'' if search_query.sort_spec.ascending else '-'}{search_query.sort_spec.attribute}"
            if search_query.sort_spec and search_query.sort_spec.attribute
            else None
        )
        ordering = self._build_ordering(request, index, current_ordering)
        facet_serializer = FacetResultSerializer(facet_result)
        payload: dict[str, Any] = {
            **facet_serializer.data,
            "results": search_result.hits,
            "total": total,
            "limit": limit,
            "offset": offset,
            "next": next_url,
            "previous": prev_url,
            "ordering": ordering,
        }
        return Response(payload)

    @action(detail=False, methods=["get"], url_path="export")
    def export(self, request: Request, index_type: str | None = None) -> Response:
        index: IndexType | None = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        raw_format = request.query_params.get("export_format") or request.query_params.get("format")
        format_name: str = (raw_format or "csv").strip().lower()
        scope: str = (request.query_params.get("scope") or "page").strip().lower()
        search_query: SearchQuery = parse_search_query(request.query_params, index, max_limit=200)
        service: SearchService = SearchService()
        rows: list[dict[str, Any]] = _collect_export_rows(service, index, search_query, scope=scope)

        if format_name == "json":
            return Response({"results": rows, "count": len(rows)})
        if format_name == "bibtex":
            if index not in (IndexType.ITEM_PARTS, IndexType.SCRIBES, IndexType.HANDS):
                return Response(
                    {"detail": "BibTeX export is supported for manuscripts, scribes, and hands."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            bibtex: str = _to_bibtex(rows, index)
            return Response({"content": bibtex})
        if format_name != "csv":
            return Response({"detail": "Unsupported export format."}, status=status.HTTP_400_BAD_REQUEST)

        output: io.StringIO = io.StringIO()
        fieldnames: list[str] = _csv_fieldnames(rows)
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
        return Response({"content": output.getvalue()})


class SearchSuggestViewSet(ViewSet):
    """Global search suggestions grouped by index type."""

    def list(self, request: Request) -> Response:
        query_text: str = (request.query_params.get("q") or "").strip()
        if len(query_text) < 2:
            return Response({"query": query_text, "suggestions": {}})

        raw_types: str = (request.query_params.get("types") or "").strip()
        if raw_types:
            requested_types: list[str] = [part.strip() for part in raw_types.split(",") if part.strip()]
            index_types: list[IndexType] = [
                URL_SEGMENT_TO_INDEX_TYPE[t] for t in requested_types if t in URL_SEGMENT_TO_INDEX_TYPE
            ]
        else:
            index_types = list(IndexType)

        try:
            requested_limit: int = int(request.query_params.get("limit") or 5)
        except (TypeError, ValueError):  # fmt: skip
            requested_limit = 5
        per_type_limit: int = min(max(requested_limit, 1), 10)
        service: SearchService = SearchService()
        suggestions = service.suggest(index_types, query_text, per_type_limit=per_type_limit)
        return Response({"query": query_text, "suggestions": suggestions})


def _collect_export_rows(
    service: SearchService,
    index: IndexType,
    search_query: SearchQuery,
    *,
    scope: str,
    max_rows: int = 2000,
) -> list[dict[str, Any]]:
    if scope != "all":
        return service.search(index, search_query).hits

    all_rows: list[dict[str, Any]] = []
    offset: int = 0
    while offset < max_rows:
        page_query = SearchQuery(
            q=search_query.q,
            filter_spec=search_query.filter_spec,
            sort_spec=search_query.sort_spec,
            limit=min(search_query.limit, 200),
            offset=offset,
            matching_strategy=search_query.matching_strategy,
            attributes_to_search_on=search_query.attributes_to_search_on,
            attributes_to_retrieve=search_query.attributes_to_retrieve,
        )
        page = service.search(index, page_query)
        if not page.hits:
            break
        all_rows.extend(page.hits)
        offset += page.limit
        if len(all_rows) >= page.total:
            break
    return all_rows[:max_rows]


def _csv_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key in seen or key == "_formatted":
                continue
            seen.add(key)
            ordered.append(key)
    return ordered


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    if isinstance(value, dict):
        return str(value)
    return str(value)


def _to_bibtex(rows: list[dict[str, Any]], index: IndexType = IndexType.ITEM_PARTS) -> str:
    entries: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if index == IndexType.SCRIBES:
            name: str = str(row.get("name") or "unknown").strip().replace(" ", "_")
            period: str = str(row.get("period") or "n.d.").strip()
            key = f"scribe_{name}_{period}".replace("/", "_")
            entries.append(
                "\n".join(
                    [
                        f"@misc{{{key},",
                        f"  author = {{{row.get('name') or ''}}},",
                        f"  title = {{Scribe: {row.get('name') or ''}}},",
                        f"  note = {{Scriptorium: {row.get('scriptorium') or 'unknown'}}},",
                        f"  year = {{{period}}},",
                        "}",
                    ]
                )
            )
        elif index == IndexType.HANDS:
            hand_name: str = str(row.get("name") or "unknown").strip().replace(" ", "_")
            repo: str = str(row.get("repository_name") or "repo").strip().replace(" ", "_")
            date: str = str(row.get("date") or "n.d.").strip()
            key = f"hand_{repo}_{hand_name}_{date}".replace("/", "_")
            entries.append(
                "\n".join(
                    [
                        f"@misc{{{key},",
                        f"  title = {{{row.get('name') or hand_name}}},",
                        f"  institution = {{{row.get('repository_name') or ''}}},",
                        f"  note = {{Shelfmark: {row.get('shelfmark') or ''}, Place: {row.get('place') or ''}}},",
                        f"  year = {{{date}}},",
                        "}",
                    ]
                )
            )
        else:
            repo = str(row.get("repository_name") or "repo").strip().replace(" ", "_")
            raw_mark = row.get("shelfmark") or row.get("display_label") or "unknown"
            shelfmark: str = str(raw_mark).strip().replace(" ", "_")
            date = str(row.get("date") or row.get("date_min") or "n.d.").strip()
            key = f"{repo}_{shelfmark}_{date}".replace("/", "_")
            entries.append(
                "\n".join(
                    [
                        f"@misc{{{key},",
                        f"  title = {{{row.get('display_label') or shelfmark}}},",
                        f"  institution = {{{row.get('repository_name') or ''}}},",
                        f"  note = {{Shelfmark: {row.get('shelfmark') or ''}}},",
                        f"  year = {{{date}}},",
                        "}",
                    ]
                )
            )
    return "\n\n".join(entries)

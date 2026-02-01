"""DRF views for search API. Parse request → service → serialize."""

from urllib.parse import urlencode

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from apps.search.api.parsers import parse_facet_attributes, parse_search_query
from apps.search.api.serializers import FacetResultSerializer, SearchResultSerializer
from apps.search.meilisearch.config import SORTABLE_ATTRIBUTES
from apps.search.services import SearchService
from apps.search.types import IndexType


class SearchViewSet(ViewSet):
    """
    Search API: list, retrieve, facets.
    index_type comes from URL (e.g. item-parts, item-images, scribes, hands, graphs).
    """

    def _get_index_type(self) -> IndexType | None:
        index_type_slug = self.kwargs.get("index_type")
        return IndexType.from_url_segment(index_type_slug) if index_type_slug else None

    def list(self, request, index_type=None):
        """GET /api/v1/search/{index_type}/"""
        index = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        search_query = parse_search_query(request.query_params, index)
        service = SearchService()
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

    def retrieve(self, request, pk=None, index_type=None):
        """GET /api/v1/search/{index_type}/{id}/"""
        index = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        service = SearchService()
        doc = service.get_document(index, pk)
        if doc is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(doc)

    def _build_ordering(self, request, index_type: IndexType, current_sort: str | None):
        """Build ordering object: current sort string and options with name, text, url."""
        allowed = list(SORTABLE_ATTRIBUTES.get(index_type, []))
        if not allowed:
            return None
        base_path = request.build_absolute_uri(request.path)
        options = []
        for attr in allowed:
            for asc, suffix in [(True, ""), (False, "-")]:
                order_val = f"{suffix}{attr}"
                params = dict(request.query_params)
                params["ordering"] = order_val
                params["offset"] = "0"
                url = f"{base_path}?{urlencode(params, doseq=True)}"
                text = f"{attr} ({'asc' if asc else 'desc'})"
                options.append({"name": order_val, "text": text, "url": url})
        return {
            "current": current_sort or (f"-{allowed[0]}" if allowed else ""),
            "options": options,
        }

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request, index_type=None):
        """GET /api/v1/search/{index_type}/facets — returns facets + results + pagination + ordering."""
        index = self._get_index_type()
        if index is None:
            return Response({"detail": "Invalid index type."}, status=status.HTTP_404_NOT_FOUND)

        search_query = parse_search_query(request.query_params, index)
        facet_attributes = parse_facet_attributes(request.query_params, index)

        service = SearchService()
        search_result = service.search(index, search_query)
        facet_result = service.get_facets(index, search_query, facet_attributes)

        total = search_result.total
        limit = search_result.limit
        offset = search_result.offset
        base_url = request.build_absolute_uri(request.path)
        params = dict(request.query_params)

        next_url = None
        if offset + limit < total:
            params["offset"] = str(offset + limit)
            next_url = f"{base_url}?{urlencode(params, doseq=True)}"
        prev_url = None
        if offset > 0:
            new_offset = max(0, offset - limit)
            params["offset"] = str(new_offset)
            prev_url = f"{base_url}?{urlencode(params, doseq=True)}"

        current_ordering = (
            f"{'' if search_query.sort_spec.ascending else '-'}{search_query.sort_spec.attribute}"
            if search_query.sort_spec and search_query.sort_spec.attribute
            else None
        )
        ordering = self._build_ordering(request, index, current_ordering)

        facet_serializer = FacetResultSerializer(facet_result)
        payload = {
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

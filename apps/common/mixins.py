from urllib.parse import urlencode
from rest_framework.decorators import action
from rest_framework.response import Response

from haystack_rest.mixins import FacetMixin as VendorFacetMixin
from haystack_rest.filters import HaystackFacetFilter, HaystackOrderingFilter

class CustomFacetMixin(VendorFacetMixin):
    """
    Extends the vendor FacetMixin to inject `ordering` hypermedia
    under `objects.ordering` without touching the vendor code.
    """

    facet_filter_backends = [
        HaystackFacetFilter,
        HaystackOrderingFilter, 
    ]

    @action(detail=False, methods=["get"], url_path="facets")
    def facets(self, request):
        response = super().facets(request)
        data = response.data

        ordering_fields = getattr(self, "ordering_fields", None)
        if ordering_fields:
            base_url = request.build_absolute_uri(request.path)
            current  = request.query_params.get(
                "ordering",
                ",".join(getattr(self, "ordering", []))
            )
            options = []
            for field in ordering_fields:
                for prefix, symbol in [("", "↑"), ("-", "↓")]:
                    term   = f"{prefix}{field}"
                    params = request.query_params.copy()
                    params["ordering"] = term
                    options.append({
                        "name": term,
                        "text": f"{field.replace('_', ' ').title()} {symbol}",
                        "url": f"{base_url}?{urlencode(params, doseq=True)}"
                    })

            data.setdefault("objects", {})
            data["objects"]["ordering"] = {
                "current": current,
                "options": options,
            }

        return Response(data)

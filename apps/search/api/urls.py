"""URL config for search API. New design: index_type in path."""

from django.urls import path

from apps.search.api.views import SearchViewSet

urlpatterns = [
    path("<index_type>/facets/", SearchViewSet.as_view({"get": "facets"}), name="search-facets"),
    path("<index_type>/<int:pk>/", SearchViewSet.as_view({"get": "retrieve"}), name="search-detail"),
    path("<index_type>/", SearchViewSet.as_view({"get": "list"}), name="search-list"),
]

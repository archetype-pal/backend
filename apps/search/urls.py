"""URL config for search API."""

from django.urls import path

from apps.search.views_management import search_action, search_stats, search_task_status
from apps.search.views_search import SearchViewSet

urlpatterns = [
    path("management/stats/", search_stats, name="management-search-stats"),
    path("management/actions/", search_action, name="management-search-actions"),
    path("management/tasks/<str:task_id>/", search_task_status, name="management-search-task-status"),
    path("<index_type>/facets/", SearchViewSet.as_view({"get": "facets"}), name="search-facets"),
    path("<index_type>/<int:pk>/", SearchViewSet.as_view({"get": "retrieve"}), name="search-detail"),
    path("<index_type>/", SearchViewSet.as_view({"get": "list"}), name="search-list"),
]

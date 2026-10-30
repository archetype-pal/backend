from django.urls import path

from apps.manuscripts.views.image_texts import ImageTextManagementViewSet
from apps.search.views_management import quality_dashboard, search_action, search_stats, search_task_status
from apps.search.views_search import SearchSuggestViewSet, SearchViewSet

urlpatterns = [
    path("management/stats/", search_stats, name="management-search-stats"),
    path("management/actions/", search_action, name="management-search-actions"),
    path("management/tasks/<str:task_id>/", search_task_status, name="management-search-task-status"),
    path("management/quality/", quality_dashboard, name="management-quality"),
    # Deprecated location; the dashboard lives at manuscripts/management/image-texts/overview/.
    # Drop once the frontend has moved.
    path("management/image-texts/overview/", ImageTextManagementViewSet.as_view({"get": "overview"})),
    path("suggest/", SearchSuggestViewSet.as_view({"get": "list"}), name="search-suggest"),
    path("<index_type>/export/", SearchViewSet.as_view({"get": "export"}), name="search-export"),
    path("<index_type>/facets/", SearchViewSet.as_view({"get": "facets"}), name="search-facets"),
    path("<index_type>/meta/", SearchViewSet.as_view({"get": "meta"}), name="search-meta"),
    path("<index_type>/<int:pk>/", SearchViewSet.as_view({"get": "retrieve"}), name="search-detail"),
    path("<index_type>/", SearchViewSet.as_view({"get": "list"}), name="search-list"),
]

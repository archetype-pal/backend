"""Admin API URL routes for search engine management."""

from django.urls import path

from .admin_views import search_action, search_stats, search_task_status

urlpatterns = [
    path("search/stats/", search_stats, name="admin-search-stats"),
    path("search/actions/", search_action, name="admin-search-actions"),
    path("search/tasks/<str:task_id>/", search_task_status, name="admin-search-task-status"),
]

"""
Aggregates all admin API routes under /api/v1/admin/.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.symbols_structure.api.admin_urls")),
    path("", include("apps.manuscripts.api.admin_urls")),
    path("", include("apps.scribes.api.admin_urls")),
    path("", include("apps.annotations.api.admin_urls")),
    path("", include("apps.publications.api.admin_urls")),
    path("", include("apps.common.api.admin_urls")),
    path("", include("apps.search.api.admin_urls")),
    path("", include("apps.users.api.admin_urls")),
]

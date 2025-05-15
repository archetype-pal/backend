from django.conf import settings
from django.contrib import admin
from django.urls import path

from .admin_views import SearchEngineAdminView


class ArcheTypeAdmin(admin.AdminSite):
    site_title = "Archetype administration"
    site_header = f"{settings.SITE_NAME} - Archetype"
    index_title = "Welcome to Archetype administration"

    def get_app_list(self, request, app_label=None):
        """
        Return a sorted list of all the installed apps that have been
        registered in this site.
        """
        app_dict = self._build_app_dict(request, app_label)

        # Desired order for apps in the admin panel
        desired_order = {
            "publications": 0,
            "common": 1,
            "manuscripts": 2,
            "scribes": 3,
            "symbols_structure": 4,
            "annotations": 5,
            "users": 6,
            "admin interface": 7,
        }

        # Sort apps based on the desired order; default to the end
        app_list = sorted(app_dict.values(), key=lambda x: desired_order.get(x["app_label"], 99))
        return app_list

    def get_urls(self):
        """
        Override the default admin URLs to add custom URLs.
        """
        urls = super().get_urls()
        custom_urls = [
            path("search-engine/", self.admin_view(SearchEngineAdminView.as_view()), name="search_engine_admin"),
        ]
        return custom_urls + urls

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from elasticsearch import Elasticsearch
from haystack.management.commands import clear_index

from apps.common.tasks import async_update_index


@method_decorator(staff_member_required, name="dispatch")
class SearchEngineAdminView(TemplateView):
    template_name = "admin/search_engine_admin.html"

    def get_search_engine(self):
        """Get the Elasticsearch instance."""
        return Elasticsearch(settings.HAYSTACK_CONNECTIONS["default"]["URL"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Admin conventional context data
        context["title"] = "Search Index Management"
        context["has_permission"] = self.request.user.is_staff

        search_engine = self.get_search_engine()
        index_name = settings.ELASTICSEARCH_INDEX

        try:
            index_exists = search_engine.indices.exists(index=index_name)
            context["no_of_records"] = search_engine.count(index=index_name)["count"] if index_exists else 0
        except Exception as e:
            context["error"] = {
                "msg": "Error connecting to Elasticsearch",
                "detail": str(e),
            }
        return context

    def post(self, request, *args, **kwargs):
        if "reindex" in request.POST:
            action = "rebuild"
        elif "clear_and_rebuild" in request.POST:
            action = "clear_and_rebuild"
        else:
            messages.error(request, "Invalid action specified.")
            return redirect(reverse("admin:search_engine_admin"))

        try:
            search_engine = self.get_search_engine()
            index_name = settings.ELASTICSEARCH_INDEX

            # Create index if it doesn't exist
            if not search_engine.indices.exists(index=index_name):
                search_engine.indices.create(index=index_name)

            if action == "clear_and_rebuild":
                clear_index.Command().handle(interactive=False)

            async_update_index.delay()

            msg = (
                "Index clearing and rebuilding started in background!"
                if action == "clear_and_rebuild"
                else "Index rebuilding started in background!"
            )
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"Error starting indexing task: {str(e)}")

        return redirect(reverse("admin:search_engine_admin"))


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Admin conventions
        context["title"] = "Search Index Management"
        context["site_title"] = "Django Administration"
        context["has_permission"] = self.request.user.is_staff

        es_url = settings.HAYSTACK_CONNECTIONS["default"]["URL"]
        es = Elasticsearch([es_url])
        index_name = settings.ELASTICSEARCH_INDEX

        try:
            # Create index if it doesn't exist
            if not es.indices.exists(index=index_name):
                es.indices.create(index=index_name)
                context["index_info"] = {"haystack": 0}
            else:
                haystack_count = es.count(index=index_name)["count"]
                context["index_info"] = {"haystack": haystack_count}
        except Exception as e:
            context["index_info"] = {
                "error": "Error connecting to Elasticsearch",
                "detail": str(e),
            }

        return context

    def post(self, request, *args, **kwargs):
        action = None
        if "reindex" in request.POST:
            action = "rebuild"
        elif "clear_and_rebuild" in request.POST:
            action = "clear_and_rebuild"

        if action:
            try:
                es_url = settings.HAYSTACK_CONNECTIONS["default"]["URL"]
                es = Elasticsearch([es_url])
                index_name = settings.ELASTICSEARCH_INDEX

                # Create index if it doesn't exist
                if not es.indices.exists(index=index_name):
                    es.indices.create(index=index_name)

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
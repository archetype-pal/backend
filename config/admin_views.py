from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.contrib.admin.views.decorators import staff_member_required
from elasticsearch import Elasticsearch


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

        try:
            haystack_count = es.count(index="haystack")["count"]
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
                if action == "clear_and_rebuild":
                    call_command("clear_index", interactive=False)

                call_command("rebuild_index", interactive=False)

                msg = (
                    "Index cleared and rebuilt successfully!"
                    if action == "clear_and_rebuild"
                    else "Index rebuilt successfully!"
                )
                messages.success(request, msg)
            except Exception as e:
                messages.error(request, f"Error during indexing: {str(e)}")

        return redirect(reverse("admin:search_engine_admin"))

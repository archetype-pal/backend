from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from haystack import connections
from haystack.constants import DJANGO_CT
from haystack.management.commands import clear_index
from haystack.utils import get_model_ct

from apps.common.tasks import (
    async_clean_and_reindex_model,
    async_clear_index_model,
    async_update_index,
    async_update_index_model,
)


def _get_index_stats():
    """Return list of dicts with per-index stats: model_label, index_name, es_count, db_count."""
    result = []
    try:
        conn = connections["default"]
        backend = conn.get_backend()
        unified_index = conn.get_unified_index()
        index_name = backend.index_name

        for model in unified_index.get_indexed_models():
            index = unified_index.get_index(model)
            model_label = f"{model._meta.app_label}.{model.__name__}"
            db_count = index.index_queryset(using="default").count()

            try:
                es_count = backend.conn.count(
                    index=index_name,
                    body={"query": {"term": {DJANGO_CT: get_model_ct(model)}}},
                )["count"]
            except Exception:
                es_count = 0

            result.append(
                {
                    "model_label": model_label,
                    "index_class_name": index.__class__.__name__,
                    "model_verbose_name": model._meta.verbose_name,
                    "model_verbose_name_plural": model._meta.verbose_name_plural,
                    "es_count": es_count,
                    "db_count": db_count,
                }
            )
    except Exception:
        pass
    return result


def _get_total_es_count():
    try:
        backend = connections["default"].get_backend()
        return backend.conn.count(index=backend.index_name)["count"]
    except Exception:
        return 0


def _format_task_error(result):
    """Extract a readable error message from a failed Celery task result."""
    if result is None:
        return "Unknown error"
    if isinstance(result, BaseException):
        return str(result) or type(result).__name__
    if isinstance(result, dict):
        msg = result.get("exc_message") or result.get("message") or result.get("error")
        if isinstance(msg, (list, tuple)):
            msg = " ".join(str(m) for m in msg)
        exc_type = result.get("exc_type", "")
        if msg and exc_type:
            return f"{exc_type}: {msg}"
        return str(msg) if msg else str(result)
    return str(result)


@staff_member_required
def search_engine_task_status(request, task_id):
    """Return Celery task status as JSON for polling."""
    from celery.result import AsyncResult

    result = AsyncResult(task_id)
    state = result.state
    info = {"state": state, "task_id": task_id}

    if state == "PROGRESS" and result.info:
        info["progress"] = result.info
    elif state == "SUCCESS" and result.result:
        info["result"] = result.result
    elif state == "FAILURE":
        info["error"] = _format_task_error(result.result)

    return JsonResponse(info)


@method_decorator(staff_member_required, name="dispatch")
class SearchEngineAdminView(TemplateView):
    template_name = "admin/search_engine_admin.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["title"] = "Search Index Management"
        context["has_permission"] = self.request.user.is_staff

        try:
            context["index_stats"] = _get_index_stats()
            context["no_of_records"] = _get_total_es_count()
            context["index_name"] = settings.ELASTICSEARCH_INDEX
        except Exception as e:
            context["error"] = {
                "msg": "Error connecting to Elasticsearch",
                "detail": str(e),
            }
            context["index_stats"] = []
            context["no_of_records"] = 0

        task_id = self.request.GET.get("task_id")
        if task_id:
            from celery.result import AsyncResult

            result = AsyncResult(task_id)
            context["task_id"] = task_id
            context["task_state"] = result.state
            context["task_result"] = result.result if result.ready() else None
            context["task_progress"] = result.info if result.state == "PROGRESS" else None
            context["task_error"] = _format_task_error(result.result) if result.failed() else None

        return context

    def post(self, request, *args, **kwargs):
        model_label = request.POST.get("model_label")
        action = None
        if "clear_index" in request.POST and model_label:
            action = ("clear", async_clear_index_model.delay(model_label))
        elif "reindex" in request.POST and model_label:
            action = ("reindex", async_update_index_model.delay(model_label))
        elif "clean_and_reindex" in request.POST and model_label:
            action = ("clean_and_reindex", async_clean_and_reindex_model.delay(model_label))
        elif "reindex" in request.POST:
            action = ("rebuild", async_update_index.delay())
        elif "clear_and_rebuild" in request.POST:
            action = ("clear_and_rebuild", None)

        if action is None:
            messages.error(request, "Invalid action specified.")
            return redirect(reverse("admin:search_engine_admin"))

        action_name, task = action

        if action_name == "clear_and_rebuild":
            try:
                clear_index.Command().handle(interactive=False)
                task = async_update_index.delay()
                messages.success(request, "Index cleared. Rebuild started in background.")
                return redirect(reverse("admin:search_engine_admin") + f"?task_id={task.id}")
            except Exception as e:
                messages.error(request, f"Error starting indexing task: {str(e)}")
            return redirect(reverse("admin:search_engine_admin"))

        if task:
            messages.success(request, "Task started. You can watch progress below.")
            return redirect(reverse("admin:search_engine_admin") + f"?task_id={task.id}")

        return redirect(reverse("admin:search_engine_admin"))

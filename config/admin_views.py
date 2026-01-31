from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from apps.search.domain import IndexType
from apps.search.infrastructure.meilisearch_writer import MeilisearchIndexWriter
from apps.search.tasks import (
    clean_and_reindex_search_index,
    clear_search_index,
    reindex_search_index,
)
from apps.search.use_cases.reindex_index import get_queryset_for_index


def _get_index_stats():
    """Return list of dicts with per-index stats: index_type, meilisearch_count, db_count."""
    result = []
    try:
        writer = MeilisearchIndexWriter()
        for index_type in IndexType:
            segment = index_type.to_url_segment()
            stats = writer.get_stats(index_type)
            meilisearch_count = stats.get("numberOfDocuments", 0)
            try:
                qs = get_queryset_for_index(index_type)
                db_count = qs.count()
            except Exception:
                db_count = 0
            result.append(
                {
                    "index_type_segment": segment,
                    "index_uid": index_type.uid,
                    "model_label": segment,
                    "index_class_name": index_type.uid,
                    "model_verbose_name": segment.replace("-", " ").title(),
                    "model_verbose_name_plural": segment.replace("-", " ").title(),
                    "es_count": meilisearch_count,
                    "db_count": db_count,
                }
            )
    except Exception:
        pass
    return result


def _get_total_meilisearch_count():
    try:
        writer = MeilisearchIndexWriter()
        total = 0
        for index_type in IndexType:
            stats = writer.get_stats(index_type)
            total += stats.get("numberOfDocuments", 0)
        return total
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
            context["no_of_records"] = _get_total_meilisearch_count()
            context["index_name"] = getattr(settings, "MEILISEARCH_URL", "Meilisearch")
        except Exception as e:
            context["error"] = {
                "msg": "Error connecting to Meilisearch",
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
        index_type_segment = request.POST.get("model_label")
        action = None
        if "clear_index" in request.POST and index_type_segment:
            action = ("clear", clear_search_index.delay(index_type_segment))
        elif "reindex" in request.POST and index_type_segment:
            action = ("reindex", reindex_search_index.delay(index_type_segment))
        elif "clean_and_reindex" in request.POST and index_type_segment:
            action = ("clean_and_reindex", clean_and_reindex_search_index.delay(index_type_segment))
        elif "reindex" in request.POST and not index_type_segment:
            for index_type in IndexType:
                reindex_search_index.delay(index_type.to_url_segment())
            messages.success(request, "Reindex all started in background.")
            return redirect(reverse("admin:search_engine_admin"))
        elif "clear_and_rebuild" in request.POST:
            from apps.search.tasks import clear_and_reindex_all_search_indexes

            task = clear_and_reindex_all_search_indexes.delay()
            messages.success(request, "Clear & Rebuild all started in background.")
            return redirect(reverse("admin:search_engine_admin") + f"?task_id={task.id}")

        if action is None:
            messages.error(request, "Invalid action specified.")
            return redirect(reverse("admin:search_engine_admin"))

        action_name, task = action
        if task:
            messages.success(request, "Task started. You can watch progress below.")
            return redirect(reverse("admin:search_engine_admin") + f"?task_id={task.id}")

        return redirect(reverse("admin:search_engine_admin"))

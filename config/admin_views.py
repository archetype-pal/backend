from django.shortcuts import render, redirect
from django.contrib import messages
from elasticsearch import Elasticsearch
from django.conf import settings
from haystack import connections

from django.core.management import call_command


def search_engine_admin(request):
    # Connect to Elasticsearch
    es_url = settings.HAYSTACK_CONNECTIONS["default"]["URL"]
    es = Elasticsearch([es_url])
    context = {}

    # Handle POST request for Reindex and Clear & Rebuild actions
    if request.method == "POST":
        if "reindex" in request.POST:
            try:
                # Rebuild the index
                call_command(
                    "rebuild_index",
                    interactive=False,
                )
                messages.success(request, "Index rebuilt successfully!")
            except Exception as e:
                messages.error(request, f"Error rebuilding index: {str(e)}")

        elif "clear_and_rebuild" in request.POST:
            try:
                # Clear the existing index
                call_command(
                    "clear_index",
                    interactive=False,
                )
                # Rebuild the index after clearing it
                call_command(
                    "rebuild_index",
                    interactive=False,
                )
                messages.success(request, "Index cleared and rebuilt successfully!")
            except Exception as e:
                messages.error(request, f"Error clearing and rebuilding index: {str(e)}")

        # After handling the POST request, redirect to the same page
        return redirect("admin:search_engine_admin")

    # Try to fetch Elasticsearch cluster info
    try:
        info = es.info()
        context["elasticsearch_info"] = info
    except Exception as e:
        context["index_info"] = {
            "error": "Error connecting to Elasticsearch",
            "detail": str(e),
        }
        return render(request, "admin/search_engine_admin.html", context)

    # Fetch the total number of records in the index
    try:
        haystack_count = es.count(index="haystack")["count"]
    except Exception as e:
        haystack_count = 0  # Default to 0 if Elasticsearch isn't responding
    context["index_info"] = {"haystack": haystack_count}

    return render(request, "admin/search_engine_admin.html", context)

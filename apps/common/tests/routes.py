"""Test helper: every (path, method) the URL conf serves under /api/v1/."""

import re

from django.urls import get_resolver
from django.urls.resolvers import URLResolver

_PARAM = re.compile(r"\(\?P<\w+>[^)]*\)|<\w+:\w+>|<\w+>")
_METHODS = ("get", "post", "put", "patch", "delete")


def _walk(patterns, prefix=""):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _walk(pattern.url_patterns, prefix + str(pattern.pattern))
        else:
            yield prefix + str(pattern.pattern), pattern.callback


def routed_operations(placeholder: str) -> set[tuple[str, str]]:
    """Every served `(path, method)` under /api/v1/, each path parameter replaced by `placeholder`.

    Only the methods a view really answers: DRF adds `head` to a viewset's
    actions on its first request, and a viewset may still refuse a routed
    method through `http_method_names` (GraphViewerWriteViewSet has no PUT).
    """
    operations: set[tuple[str, str]] = set()
    for route, callback in _walk(get_resolver().url_patterns):
        if not route.startswith("api/v1/"):
            continue
        path = "/" + _PARAM.sub(placeholder, route.replace("^", "").replace("$", ""))
        view = getattr(callback, "cls", callback)
        actions = getattr(callback, "actions", None)
        methods = {m for m in _METHODS if m in (actions or ()) or hasattr(view, m)}
        if actions:
            methods &= set(actions)
        allowed = getattr(view, "http_method_names", None)
        if allowed:
            methods &= set(allowed)
        operations.update((path, method) for method in methods)
    return operations

"""Every management operation is superuser-only: anonymous callers get 401, signed-in non-superusers 403.

One contract test over the routed URL tree, so a new management endpoint is
covered the moment it is routed and no endpoint needs its own permission tests.
DRF checks permissions before looking the object up, so a placeholder id is enough.
"""

import re

from django.urls import get_resolver
from django.urls.resolvers import URLResolver
import pytest


def _management_operations() -> list[tuple[str, str]]:
    def walk(patterns, prefix=""):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, prefix + str(pattern.pattern))
            else:
                yield prefix + str(pattern.pattern), pattern.callback

    operations: list[tuple[str, str]] = []
    for route, callback in walk(get_resolver().url_patterns):
        if not route.startswith("api/v1/") or "management/" not in route:
            continue
        path = "/" + re.sub(r"\(\?P<\w+>[^)]*\)|<\w+:\w+>|<\w+>", "1", route.replace("^", "").replace("$", ""))
        view = getattr(callback, "cls", callback)
        actions = getattr(callback, "actions", None)
        methods = actions or {m: m for m in ("get", "post", "put", "patch", "delete") if hasattr(view, m)}
        operations.extend((path, method) for method in methods)
    return sorted(set(operations))


MANAGEMENT_OPERATIONS = _management_operations()


def test_the_management_surface_is_not_empty():
    assert len(MANAGEMENT_OPERATIONS) > 50


@pytest.mark.django_db
def test_anonymous_callers_are_rejected_from_every_management_operation(api_client):
    leaks = [
        (method.upper(), path)
        for path, method in MANAGEMENT_OPERATIONS
        if getattr(api_client, method)(path).status_code != 401
    ]
    assert not leaks, "Management operations reachable anonymously:\n" + "\n".join(f"{m} {p}" for m, p in leaks)


@pytest.mark.django_db
def test_non_superusers_are_rejected_from_every_management_operation(authenticated_client):
    leaks = [
        (method.upper(), path)
        for path, method in MANAGEMENT_OPERATIONS
        if getattr(authenticated_client, method)(path).status_code != 403
    ]
    assert not leaks, "Management operations open to non-superusers:\n" + "\n".join(f"{m} {p}" for m, p in leaks)

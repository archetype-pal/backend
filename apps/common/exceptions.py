"""Project-wide DRF exception handling (config.settings EXCEPTION_HANDLER)."""

from collections import Counter

from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


def drf_exception_handler(exc, context) -> Response | None:
    """Map Django's ProtectedError to 409 instead of an unhandled 500.

    A delete blocked by on_delete=PROTECT is a data conflict, not a server
    fault: the request is valid, other rows just still reference the target.
    The `detail` string names the blockers; the backoffice error toasts
    already render `detail`, so no frontend change is needed.
    """
    if isinstance(exc, ProtectedError):
        counts = Counter(type(obj)._meta for obj in exc.protected_objects)
        parts = [
            f"{count} {meta.verbose_name if count == 1 else meta.verbose_name_plural}"
            for meta, count in sorted(counts.items(), key=lambda item: (-item[1], str(item[0].verbose_name)))
        ]
        detail = f"Cannot delete: still referenced by {', '.join(parts)}."
        return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)
    return exception_handler(exc, context)

from rest_framework.permissions import BasePermission


class IsSuperuser(BasePermission):
    """Allows access only to authenticated superusers."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)

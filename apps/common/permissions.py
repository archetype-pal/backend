from rest_framework.permissions import BasePermission


def is_authenticated_superuser(user) -> bool:
    return bool(user and user.is_authenticated and user.is_superuser)


class IsSuperuser(BasePermission):
    """Allows access only to authenticated superusers."""

    def has_permission(self, request, view):
        return is_authenticated_superuser(request.user)

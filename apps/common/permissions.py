from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_authenticated_superuser(user) -> bool:
    return bool(user and user.is_authenticated and user.is_superuser)


class IsSuperuser(BasePermission):
    """Allows access only to authenticated superusers."""

    def has_permission(self, request, view):
        return is_authenticated_superuser(request.user)


class IsOwnerOrReadOnly(BasePermission):
    """Object-level: safe methods for anyone, writes only for the object's owner.

    Relies on the object exposing an ``owner_id``/``owner`` attribute. Note this
    only runs on detail (get_object) actions — list/create safety must be
    enforced by the viewset's queryset scoping.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user and request.user.is_authenticated and getattr(obj, "owner_id", None) == request.user.id
        )

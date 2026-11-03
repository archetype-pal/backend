from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_authenticated_superuser(user) -> bool:
    return bool(user and user.is_authenticated and user.is_superuser)


# What a user may do, by name. The permission classes and querysets below and across the apps
# use these predicates, and the profile states them as `capabilities`, so the frontend gates on
# the same answers the API enforces instead of reading the raw flags.


def can_annotate(user) -> bool:
    """Draw, edit and delete image and text annotations in the viewer."""
    return bool(user and user.is_authenticated)


def can_annotate_editorially(user) -> bool:
    """Create and change editorial annotations."""
    return is_authenticated_superuser(user)


def can_read_drafts(user) -> bool:
    """Read texts in every status, not just the published ones. Staff, the student tier, may;
    a superuser may too, whether or not they are also staff."""
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def can_manage(user) -> bool:
    """Use the management API, and so the backoffice."""
    return is_authenticated_superuser(user)


def capabilities(user) -> dict[str, bool]:
    return {
        "annotate": can_annotate(user),
        "annotate_editorially": can_annotate_editorially(user),
        "read_drafts": can_read_drafts(user),
        "manage": can_manage(user),
    }


class IsSuperuser(BasePermission):
    """Allows access only to authenticated superusers."""

    def has_permission(self, request, view):
        return can_manage(request.user)


class CanAnnotate(BasePermission):
    """Allows access to users who may annotate (`can_annotate`)."""

    def has_permission(self, request, view):
        return can_annotate(request.user)


class IsSuperuserOrReadOnly(BasePermission):
    """Allows safe methods to anyone, writes only to authenticated superusers."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
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

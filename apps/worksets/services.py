"""Application services for the worksets app — queryset scoping lives here so
the viewset stays transport-only."""

from django.db.models import Q, QuerySet

from .models import Workset


def get_owned_worksets_queryset(user) -> QuerySet[Workset]:
    """Worksets the given user owns (empty for anonymous users)."""
    if not (user and user.is_authenticated):
        return Workset.objects.none()
    return Workset.objects.filter(owner=user).select_related("owner")


def get_citable_worksets_queryset(user) -> QuerySet[Workset]:
    """Worksets readable via a citable link: any Public one, plus the caller's own.

    Scoping retrieve to this set means a Private workset 404s for anyone but its
    owner, rather than leaking its existence.
    """
    public = Q(visibility=Workset.Visibility.PUBLIC)
    if user and user.is_authenticated:
        return Workset.objects.filter(public | Q(owner=user)).select_related("owner")
    return Workset.objects.filter(public).select_related("owner")

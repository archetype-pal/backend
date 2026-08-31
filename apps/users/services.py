"""Application services for user management workflows."""

from datetime import timedelta
import secrets
from typing import cast

from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.audit import log_edit
from apps.common.models import EditEvent

from .models import ImpersonationToken

IMPERSONATION_TTL = timedelta(hours=1)


def impersonate_user(*, actor: AbstractUser, target: AbstractUser) -> ImpersonationToken:
    """Let a superuser browse the app as *target* without knowing their password.

    This project authenticates via DRF token auth, not server-side sessions, so
    there is no session to swap the way `django-impersonate`'s middleware does.
    Instead we mint a separate, expiring credential that authenticates as the
    target while recording who is driving it (see `ImpersonationToken`).

    Restricted to genuine "support" impersonation: never yourself, and never
    another staff/superuser account (that would let a superuser silently
    assume another admin's privileges without their knowledge).
    """
    if actor.pk == target.pk:
        raise ValidationError("You cannot impersonate yourself.")
    if target.is_staff or target.is_superuser:
        raise PermissionDenied("Cannot impersonate a staff or superuser account.")
    if not target.is_active:
        raise ValidationError("Cannot impersonate an inactive account.")

    token: ImpersonationToken = ImpersonationToken.objects.create(
        key=secrets.token_hex(20),
        user=target,
        impersonated_by=actor,
        expires=timezone.now() + IMPERSONATION_TTL,
    )

    log_edit(
        actor=actor,
        action=cast(str, EditEvent.Action.IMPERSONATED),
        target_type="user",
        target_id=target.pk,
        summary=f"{actor} impersonated {target}",
    )

    return token

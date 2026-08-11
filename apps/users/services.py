"""Application services for user management workflows."""

from typing import cast

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.audit import log_edit
from apps.common.models import EditEvent

User = get_user_model()


def impersonate_user(*, actor: AbstractBaseUser, target: AbstractBaseUser) -> Token:
    """Let a superuser browse the app as *target* without knowing their password.

    This project authenticates via DRF `TokenAuthentication` (bearer tokens),
    not server-side sessions, so there is no session to swap the way
    `django-impersonate`'s middleware does. Instead we hand the caller the
    target's own auth token (minted on first use) so the frontend can swap
    its stored token and make subsequent requests as that user.

    Restricted to genuine "support" impersonation: never yourself, and never
    another staff/superuser account (that would let a superuser silently
    assume another admin's privileges without their knowledge).
    """
    if actor.pk == target.pk:
        raise ValidationError("You cannot impersonate yourself.")
    if target.is_staff or target.is_superuser:
        raise PermissionDenied("Cannot impersonate a staff or superuser account.")

    token, _ = Token.objects.get_or_create(user=target)

    log_edit(
        actor=actor,
        action=cast(str, EditEvent.Action.IMPERSONATED),
        target_type="user",
        target_id=target.pk,
        summary=f"{actor} impersonated {target}",
    )

    return token

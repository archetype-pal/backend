"""Lightweight audit-trail helpers for the EditEvent log.

The event-log table itself lives in ``apps.common`` because every other app is
allowed to import it. The signal handlers, however, must touch tables that
``common`` cannot import, so each owning app wires its own post_save /
post_delete handlers in its ``apps.py`` ready hook (see
``apps.annotations.apps`` and ``apps.manuscripts.apps``).
"""

from __future__ import annotations

from contextlib import contextmanager
import contextvars
from typing import Any, cast

from django.contrib.auth import get_user_model
from django.db.models import Model

from apps.common.models import EditEvent

User = get_user_model()

# The acting user for the current request. DRF resolves `request.user` in the
# view layer (token auth), not in Django middleware, so the actor is set around
# each write via `audit_actor(...)` (see `AuditActorMixin`). The signal handlers
# read it as a fallback when the saved/deleted instance has no explicit
# `_audit_actor` attribute.
_current_actor: contextvars.ContextVar[Any | None] = contextvars.ContextVar("audit_actor", default=None)


@contextmanager
def audit_actor(actor: Any | None):
    """Bind *actor* as the current audit actor for the duration of the block.

    Self-cleaning (resets in ``finally``), so it is safe on reused worker
    threads — the actor never leaks into a later request.
    """
    token = _current_actor.set(actor if isinstance(actor, User) else None)
    try:
        yield
    finally:
        _current_actor.reset(token)


def _resolve_actor(instance: Model) -> Any | None:
    """Prefer an actor explicitly attached to the instance, else the bound one."""
    actor = getattr(instance, "_audit_actor", None)
    if isinstance(actor, User):
        return actor
    return _current_actor.get()


def log_edit(
    *,
    actor: Any | None,
    action: str,
    target_type: str,
    target_id: int,
    summary: str = "",
    payload: dict | None = None,
) -> None:
    # Set by ImpersonationTokenAuthentication on the user it returns, so every
    # event of an impersonated session — signals included — names the driver.
    impersonator = getattr(actor, "impersonated_by", None)
    if impersonator is not None:
        payload = {**(payload or {}), "impersonated_by": impersonator.username}

    EditEvent.objects.create(
        actor=actor if isinstance(actor, User) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary[:255],
        payload=payload,
    )


def _resolve_action(sender: type[Model], instance: Model, created: bool, update_fields: frozenset[str] | None) -> str:
    """Trash and restore are `save()`s, so they would otherwise log as `updated`.

    Derive their verb from the *shape of the write* rather than from a flag the
    caller has to remember to set: `SoftDeleteModel.soft_delete()`/`restore()`
    write exactly `TRASH_AUDIT_FIELDS` and nothing else, so that signature
    identifies the action, and `deleted_at` says which of the two it is.
    Models without the attribute (everything not soft-deletable) fall straight
    through to the ordinary created/updated pair.
    """
    trash_fields = getattr(sender, "TRASH_AUDIT_FIELDS", None)
    if trash_fields and update_fields and frozenset(update_fields) == trash_fields:
        if getattr(instance, "deleted_at", None) is not None:
            return cast(str, EditEvent.Action.TRASHED)
        return cast(str, EditEvent.Action.RESTORED)
    return cast(str, EditEvent.Action.CREATED if created else EditEvent.Action.UPDATED)


def on_save_handler(
    sender: type[Model],
    instance: Model,
    created: bool,
    update_fields: frozenset[str] | None = None,
    **_: Any,
) -> None:
    target_type = sender._meta.model_name or sender.__name__.lower()
    actor = _resolve_actor(instance)
    summary = ""
    try:
        summary = str(instance)[:255]
    except Exception:
        summary = ""
    # Popped, not read: a payload must never survive into a later save of the
    # same in-memory instance.
    payload = instance.__dict__.pop("_audit_payload", None)
    log_edit(
        actor=actor,
        action=_resolve_action(sender, instance, created, update_fields),
        target_type=target_type,
        target_id=getattr(instance, "pk", 0) or 0,
        summary=summary,
        payload=payload,
    )


def on_delete_handler(sender: type[Model], instance: Model, **_: Any) -> None:
    target_type = sender._meta.model_name or sender.__name__.lower()
    actor = _resolve_actor(instance)
    summary = str(instance)[:255] if instance else ""
    log_edit(
        actor=actor,
        action=cast(str, EditEvent.Action.DELETED),
        target_type=target_type,
        target_id=getattr(instance, "pk", 0) or 0,
        summary=summary,
    )


def register_audited_models(*models: type[Model]) -> None:
    """Connect ``post_save`` / ``post_delete`` to each model. Idempotent.

    Each owning app calls this once from its ``AppConfig.ready()`` so that
    ``apps.common`` doesn't have to import models from apps it isn't allowed
    to depend on.
    """
    from django.db.models.signals import post_delete, post_save

    for model in models:
        post_save.connect(on_save_handler, sender=model, dispatch_uid=f"editevent:{model.__name__}:save")
        post_delete.connect(on_delete_handler, sender=model, dispatch_uid=f"editevent:{model.__name__}:delete")

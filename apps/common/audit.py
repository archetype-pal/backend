"""Lightweight audit-trail helpers for the EditEvent log.

The event-log table itself lives in ``apps.common`` because every other app is
allowed to import it. The signal handlers, however, must touch tables that
``common`` cannot import, so each owning app wires its own post_save /
post_delete handlers in its ``apps.py`` ready hook (see
``apps.annotations.apps`` and ``apps.manuscripts.apps``).
"""

from __future__ import annotations

from typing import Any, cast

from django.contrib.auth import get_user_model
from django.db.models import Model

from apps.common.models import EditEvent

User = get_user_model()


def log_edit(
    *,
    actor: Any | None,
    action: str,
    target_type: str,
    target_id: int,
    summary: str = "",
    payload: dict | None = None,
) -> None:
    EditEvent.objects.create(
        actor=actor if isinstance(actor, User) else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary[:255],
        payload=payload,
    )


def on_save_handler(sender: type[Model], instance: Model, created: bool, **_: Any) -> None:
    target_type = sender._meta.model_name or sender.__name__.lower()
    actor = getattr(instance, "_audit_actor", None)
    summary = ""
    try:
        summary = str(instance)[:255]
    except Exception:
        summary = ""
    log_edit(
        actor=actor,
        action=cast(str, EditEvent.Action.CREATED if created else EditEvent.Action.UPDATED),
        target_type=target_type,
        target_id=getattr(instance, "pk", 0) or 0,
        summary=summary,
    )


def on_delete_handler(sender: type[Model], instance: Model, **_: Any) -> None:
    target_type = sender._meta.model_name or sender.__name__.lower()
    actor = getattr(instance, "_audit_actor", None)
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

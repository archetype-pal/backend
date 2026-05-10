"""Tests for the EditEvent audit-log helpers.

Pinned behaviour:
  - log_edit creates an EditEvent with the actor (only when it's a real user)
  - on_save_handler emits CREATED on first insert, UPDATED on subsequent saves
  - on_delete_handler emits DELETED
  - summary is truncated to 255 chars and falls back to "" if str(instance) raises
  - register_audited_models is idempotent — calling twice doesn't double-emit
"""

from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
import pytest

from apps.common.audit import (
    log_edit,
    on_delete_handler,
    on_save_handler,
    register_audited_models,
)
from apps.common.models import EditEvent

User = get_user_model()


@pytest.mark.django_db
class TestLogEdit:
    def test_creates_event_with_actor(self):
        user = User.objects.create(username="alice")
        log_edit(
            actor=user,
            action=EditEvent.Action.CREATED,
            target_type="graph",
            target_id=42,
            summary="hello",
        )
        event = EditEvent.objects.get()
        assert event.actor == user
        assert event.action == EditEvent.Action.CREATED
        assert event.target_type == "graph"
        assert event.target_id == 42
        assert event.summary == "hello"

    def test_drops_actor_when_not_a_user(self):
        # log_edit accepts any object as actor but only persists it if it
        # is actually a User instance — protects against passing string IDs
        # or stale references.
        log_edit(
            actor="not-a-user",
            action=EditEvent.Action.UPDATED,
            target_type="graph",
            target_id=1,
        )
        event = EditEvent.objects.get()
        assert event.actor is None

    def test_summary_truncated_at_255(self):
        log_edit(
            actor=None,
            action=EditEvent.Action.UPDATED,
            target_type="graph",
            target_id=1,
            summary="x" * 500,
        )
        event = EditEvent.objects.get()
        assert len(event.summary) == 255

    def test_payload_round_trip(self):
        log_edit(
            actor=None,
            action=EditEvent.Action.STATUS_CHANGED,
            target_type="imagetext",
            target_id=7,
            payload={"from": "Draft", "to": "Live"},
        )
        event = EditEvent.objects.get()
        assert event.payload == {"from": "Draft", "to": "Live"}


class _FakeSender:
    """Stand-in for a model class — only `_meta.model_name` and `__name__` are read."""

    __name__ = "FakeModel"
    _meta = SimpleNamespace(model_name="fakemodel")


@pytest.mark.django_db
class TestOnSaveHandler:
    def test_created_action_when_created_true(self):
        instance = SimpleNamespace(pk=1, _audit_actor=None)
        on_save_handler(sender=_FakeSender, instance=instance, created=True)
        event = EditEvent.objects.get()
        assert event.action == EditEvent.Action.CREATED
        assert event.target_type == "fakemodel"
        assert event.target_id == 1

    def test_updated_action_when_created_false(self):
        instance = SimpleNamespace(pk=1, _audit_actor=None)
        on_save_handler(sender=_FakeSender, instance=instance, created=False)
        event = EditEvent.objects.get()
        assert event.action == EditEvent.Action.UPDATED

    def test_falls_back_to_classname_when_no_meta_model_name(self):
        sender = type("Bare", (), {"__name__": "Bare", "_meta": SimpleNamespace(model_name=None)})
        instance = SimpleNamespace(pk=99, _audit_actor=None)
        on_save_handler(sender=sender, instance=instance, created=True)
        event = EditEvent.objects.get()
        assert event.target_type == "bare"

    def test_summary_falls_back_to_empty_when_str_raises(self):
        # If __str__ blows up (broken model state), the handler should still
        # log the event with an empty summary instead of bubbling the error.
        class _ExplodingStr:
            pk = 5
            _audit_actor = None

            def __str__(self):
                raise RuntimeError("kaboom")

        on_save_handler(sender=_FakeSender, instance=_ExplodingStr(), created=True)
        event = EditEvent.objects.get()
        assert event.summary == ""

    def test_actor_is_picked_up_from_audit_actor(self):
        user = User.objects.create(username="bob")
        instance = SimpleNamespace(pk=11, _audit_actor=user)
        on_save_handler(sender=_FakeSender, instance=instance, created=True)
        event = EditEvent.objects.get()
        assert event.actor == user

    def test_target_id_zero_when_pk_missing(self):
        instance = SimpleNamespace(pk=None, _audit_actor=None)
        on_save_handler(sender=_FakeSender, instance=instance, created=True)
        event = EditEvent.objects.get()
        assert event.target_id == 0


@pytest.mark.django_db
class TestOnDeleteHandler:
    def test_emits_deleted_action(self):
        instance = SimpleNamespace(pk=3, _audit_actor=None)
        on_delete_handler(sender=_FakeSender, instance=instance)
        event = EditEvent.objects.get()
        assert event.action == EditEvent.Action.DELETED
        assert event.target_type == "fakemodel"
        assert event.target_id == 3


@pytest.mark.django_db
class TestRegisterAuditedModels:
    def test_register_is_idempotent(self):
        # Two calls with the same model should not result in two events
        # per save — dispatch_uid de-duplicates the connection.
        from apps.users.tests.factories import UserFactory

        register_audited_models(User)
        register_audited_models(User)
        try:
            EditEvent.objects.all().delete()
            UserFactory()
            assert EditEvent.objects.filter(target_type="user").count() == 1
        finally:
            # Clean up the connection so other tests don't leak this signal.
            post_save.disconnect(on_save_handler, sender=User, dispatch_uid="editevent:User:save")
            post_delete.disconnect(on_delete_handler, sender=User, dispatch_uid="editevent:User:delete")

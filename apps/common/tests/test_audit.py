"""The EditEvent audit log, exercised through a real audited model (`ImageText`)."""

from django.db.models.signals import post_delete, post_save
import pytest

from apps.common.audit import audit_actor, log_edit, on_delete_handler, on_save_handler, register_audited_models
from apps.common.models import EditEvent
from apps.manuscripts.tests.factories import ImageTextFactory
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_save_and_delete_are_logged_with_the_bound_actor():
    user = UserFactory()
    with audit_actor(user):
        text = ImageTextFactory()
        text.language = "la"
        text.save()
        pk = text.pk
        text.delete()

    events = EditEvent.objects.filter(target_type="imagetext", target_id=pk).order_by("id")
    assert [event.action for event in events] == ["created", "updated", "deleted"]
    assert {event.actor for event in events} == {user}


def test_outside_an_actor_scope_the_actor_is_none():
    text = ImageTextFactory()

    assert EditEvent.objects.get(target_type="imagetext", target_id=text.pk).actor is None


def test_an_actor_attached_to_the_instance_wins_over_the_bound_one():
    bound, attached = UserFactory(), UserFactory()
    text = ImageTextFactory()
    with audit_actor(bound):
        text._audit_actor = attached
        text.save()

    assert EditEvent.objects.filter(target_id=text.pk, action="updated").get().actor == attached


def test_a_non_user_actor_is_dropped_and_a_long_summary_is_truncated():
    log_edit(actor="not-a-user", action=EditEvent.Action.UPDATED, target_type="graph", target_id=1, summary="x" * 500)

    event = EditEvent.objects.get()
    assert event.actor is None
    assert len(event.summary) == 255


def test_a_payload_is_stored_once_and_not_replayed_on_the_next_save():
    text = ImageTextFactory()
    text._audit_payload = {"from": "Draft", "to": "Live"}
    text.save()
    text.save()

    payloads = [e.payload for e in EditEvent.objects.filter(target_id=text.pk, action="updated").order_by("id")]
    assert payloads == [{"from": "Draft", "to": "Live"}, None]


def test_registering_a_model_twice_does_not_double_log():
    User = UserFactory._meta.model
    register_audited_models(User)
    register_audited_models(User)
    try:
        EditEvent.objects.all().delete()
        UserFactory()
        assert EditEvent.objects.filter(target_type="user").count() == 1
    finally:
        post_save.disconnect(on_save_handler, sender=User, dispatch_uid="editevent:User:save")
        post_delete.disconnect(on_delete_handler, sender=User, dispatch_uid="editevent:User:delete")

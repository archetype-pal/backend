"""The pre-AI throughput baseline — AI programme W0.5.

The headline first-year claim is a throughput improvement, so the "before" has
to be honest about what it can and cannot count.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
import pytest

from apps.common.models import EditEvent


def _created_event(*, actor, when):
    event = EditEvent.objects.create(
        actor=actor, action=EditEvent.Action.CREATED, target_type="graph", target_id=1
    )
    # `created` is auto_now_add, so the window has to be staged after the fact.
    EditEvent.objects.filter(pk=event.pk).update(created=when)
    return event


def _run(**kwargs) -> str:
    out = StringIO()
    call_command("annotation_throughput", stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
class TestWindow:
    def test_counts_annotations_per_annotator(self, django_user_model):
        annotator = django_user_model.objects.create_user(username="ada", password="x")
        now = timezone.now()
        for _ in range(3):
            _created_event(actor=annotator, when=now - timedelta(days=1))

        output = _run(since=(now - timedelta(days=7)).strftime("%Y-%m-%d"))

        assert "ada" in output
        assert "annotations=3" in output
        assert "total: 3 annotations by 1 annotators" in output

    def test_events_outside_the_window_do_not_count(self, django_user_model):
        annotator = django_user_model.objects.create_user(username="ada", password="x")
        now = timezone.now()
        _created_event(actor=annotator, when=now - timedelta(days=90))

        output = _run(since=(now - timedelta(days=7)).strftime("%Y-%m-%d"))

        assert "No annotations created in this window." in output

    def test_an_inverted_window_is_an_error(self):
        with pytest.raises(CommandError, match="must be after"):
            _run(since="2026-08-01", until="2026-07-01")

    def test_an_unreadable_date_is_an_error(self):
        with pytest.raises(CommandError, match="YYYY-MM-DD"):
            _run(since="last tuesday")


@pytest.mark.django_db
class TestHonesty:
    def test_says_what_the_number_is_not(self, django_user_model):
        """The migrated corpus is not a baseline, and the output must say so."""
        annotator = django_user_model.objects.create_user(username="ada", password="x")
        _created_event(actor=annotator, when=timezone.now() - timedelta(days=1))

        output = _run(since=(timezone.now() - timedelta(days=7)).strftime("%Y-%m-%d"))

        assert "carry a creation event" in output
        assert "corpus size is not a throughput measurement" in output

    def test_the_note_appears_even_with_no_activity(self):
        output = _run(since=(timezone.now() - timedelta(days=7)).strftime("%Y-%m-%d"))

        assert "carry a creation event" in output

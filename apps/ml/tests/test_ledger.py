"""The inference ledger — W0.1.

The ledger's whole justification is that provenance cannot be reconstructed
after the fact, so these tests pin the properties that make it trustworthy: a
row exists before the provider runs, success and provenance land together, and
a record can be traced back to what produced it.
"""

from django.db import IntegrityError, transaction
import pytest

from apps.ml.models import MLJob, MLJobTarget
from apps.ml.providers import InferenceResult, content_digest
from apps.ml.services import ledger

from .factories import MLJobFactory, MLJobTargetFactory


class TestContentDigest:
    def test_is_stable_across_key_order(self):
        assert content_digest({"a": 1, "b": 2}) == content_digest({"b": 2, "a": 1})

    def test_differs_on_different_content(self):
        assert content_digest({"a": 1}) != content_digest({"a": 2})


@pytest.mark.django_db
class TestOpenJob:
    def test_opens_pending_before_anything_runs(self):
        job = ledger.open_job(task="W1.1", provider="null", inputs={"x": 1})

        assert job.status == MLJob.Status.PENDING
        assert job.task == "W1.1"
        assert job.provider == "null"

    def test_anonymous_actor_is_not_recorded(self):
        job = ledger.open_job(task="W1.1", provider="null", inputs={}, actor=None)

        assert job.actor is None


@pytest.mark.django_db
class TestRecordOutcome:
    def test_success_records_model_cost_and_targets_together(self):
        job = ledger.open_job(task="W1.1", provider="null", inputs={})
        result = InferenceResult(
            output={},
            model_name="some-model",
            model_version="2026-01",
            prompt_hash="a" * 64,
            input_tokens=11,
            output_tokens=22,
            cost_micros=1234,
            cost_currency="USD",
        )

        job = ledger.record_success(job, result, duration_ms=42, targets=[("graph", 7)])

        assert job.status == MLJob.Status.SUCCEEDED
        assert job.model_name == "some-model"
        assert job.model_version == "2026-01"
        assert (job.input_tokens, job.output_tokens) == (11, 22)
        assert job.cost_micros == 1234
        assert job.duration_ms == 42
        assert list(job.targets.values_list("target_type", "target_id")) == [("graph", 7)]

    def test_failure_truncates_an_unbounded_provider_error(self):
        job = ledger.open_job(task="W1.1", provider="null", inputs={})

        job = ledger.record_failure(job, "x" * 9000, duration_ms=3)

        assert job.status == MLJob.Status.FAILED
        assert len(job.error) == 4000

    def test_refusal_is_a_ledger_row_not_a_silence(self):
        job = ledger.open_job(task="W1.1", provider="null", inputs={})

        job = ledger.record_refusal(job, "cap reached")

        assert job.status == MLJob.Status.REFUSED
        assert job.error == "cap reached"
        assert job.cost_micros == 0


@pytest.mark.django_db
class TestTargets:
    def test_reattaching_the_same_target_is_idempotent(self):
        job = MLJobFactory()

        ledger.attach_targets(job, [("graph", 1), ("graph", 2)])
        ledger.attach_targets(job, [("graph", 2), ("graph", 3)])

        assert job.targets.count() == 3

    def test_the_same_target_cannot_be_recorded_twice_for_one_job(self):
        target = MLJobTargetFactory()

        with pytest.raises(IntegrityError), transaction.atomic():
            MLJobTarget.objects.create(
                job=target.job,
                target_type=target.target_type,
                target_id=target.target_id,
            )

    def test_jobs_touching_answers_which_model_produced_this_record(self):
        wanted = MLJobFactory(model_name="detector-v1")
        MLJobTargetFactory(job=wanted, target_type="graph", target_id=99)
        other = MLJobFactory(model_name="something-else")
        MLJobTargetFactory(job=other, target_type="graph", target_id=100)

        found = ledger.jobs_touching("graph", 99)

        assert [job.model_name for job in found] == ["detector-v1"]

    def test_deleting_a_job_removes_its_targets(self):
        target = MLJobTargetFactory()

        target.job.delete()

        assert MLJobTarget.objects.count() == 0


@pytest.mark.django_db
class TestLedgerIsNotAudited:
    def test_writing_a_job_produces_no_edit_event(self):
        """The ledger is itself the log; auditing it would double-log every call."""
        from apps.common.models import EditEvent

        before = EditEvent.objects.count()
        MLJobFactory()

        assert EditEvent.objects.count() == before

"""The inference application service and its task — W0.1.

The invariant under test is the architectural one: an inference produces a
proposal and a ledger row, and never a canonical record.
"""

from unittest import mock

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult, ProviderError, UnknownProvider
from apps.ml.services import InferenceService
from apps.ml.tasks import run_inference


class _Boom:
    def run(self, request: InferenceRequest) -> InferenceResult:
        raise ProviderError("provider exploded")


class _Claiming:
    """A provider that names records its output is about."""

    def run(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(
            output={"targets": [{"type": "graph", "id": 5}, {"type": "graph", "id": 6}, "nonsense"]},
            model_name="claimer",
            cost_micros=25,
            cost_currency="USD",
        )


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


@pytest.mark.django_db
class TestSubmit:
    def test_unknown_provider_is_rejected_before_a_row_is_opened(self, enabled):
        with pytest.raises(UnknownProvider, match="not-a-provider"):
            InferenceService().submit(task="W1.1", provider="not-a-provider", inputs={})

        assert MLJob.objects.count() == 0

    def test_submitting_opens_a_row_and_enqueues_after_commit(self, enabled, django_capture_on_commit_callbacks):
        with mock.patch("apps.ml.tasks.run_inference") as task:
            with django_capture_on_commit_callbacks(execute=True):
                job = InferenceService().submit(task="W1.1", provider="null", inputs={"a": 1})

        task.delay.assert_called_once_with(job.pk, {"a": 1}, {})

    def test_the_input_digest_is_recorded_but_not_the_inputs(self, enabled):
        job = InferenceService().submit(task="W1.1", provider="null", inputs={"secret": "corpus text"})

        assert len(job.input_ref) == 64
        assert "corpus text" not in job.input_ref

    def test_a_disabled_switch_refuses_without_dispatching(self, settings, django_capture_on_commit_callbacks):
        settings.ML_INFERENCE_ENABLED = False

        with mock.patch("apps.ml.tasks.run_inference") as task:
            with django_capture_on_commit_callbacks(execute=True):
                job = InferenceService().submit(task="W1.1", provider="null", inputs={})

        assert job.status == MLJob.Status.REFUSED
        task.delay.assert_not_called()

    def test_a_hosted_provider_is_gated_separately_from_cost(self, enabled):
        """Sending corpus material off our infrastructure is its own decision."""
        with mock.patch.dict(
            "apps.ml.providers.registry.PROVIDER_REGISTRY",
            {"hosted-thing": _hosted_registration()},
        ):
            job = InferenceService().submit(task="W1.1", provider="hosted-thing", inputs={})

        assert job.status == MLJob.Status.REFUSED
        assert "hosted" in job.error

    def test_a_hosted_provider_runs_once_the_policy_allows_it(self, enabled):
        enabled.ML_HOSTED_PROVIDERS_ENABLED = True

        with mock.patch.dict(
            "apps.ml.providers.registry.PROVIDER_REGISTRY",
            {"hosted-thing": _hosted_registration()},
        ):
            job = InferenceService().submit(task="W1.1", provider="hosted-thing", inputs={})

        assert job.status == MLJob.Status.PENDING


@pytest.mark.django_db
class TestRun:
    def test_a_successful_run_closes_the_row(self, enabled):
        job = InferenceService().submit(task="W1.1", provider="null", inputs={"a": 1})

        job = InferenceService().run(job.pk, inputs={"a": 1}, celery_task_id="task-123")

        assert job.status == MLJob.Status.SUCCEEDED
        assert job.model_name == "null"
        assert job.celery_task_id == "task-123"
        assert job.duration_ms is not None

    def test_a_provider_error_is_recorded_not_raised(self, enabled):
        job = InferenceService().submit(task="W1.1", provider="null", inputs={})

        with mock.patch.dict(
            "apps.ml.providers.registry.PROVIDER_REGISTRY",
            {"null": _registration(factory=_Boom)},
        ):
            job = InferenceService().run(job.pk, inputs={})

        assert job.status == MLJob.Status.FAILED
        assert "provider exploded" in job.error

    def test_declared_targets_are_recorded_and_malformed_ones_ignored(self, enabled):
        job = InferenceService().submit(task="W1.1", provider="null", inputs={})

        with mock.patch.dict(
            "apps.ml.providers.registry.PROVIDER_REGISTRY",
            {"null": _registration(factory=_Claiming)},
        ):
            job = InferenceService().run(job.pk, inputs={})

        assert sorted(job.targets.values_list("target_id", flat=True)) == [5, 6]

    def test_a_provider_cannot_reach_the_canonical_record(self, enabled):
        """`apps.ml` imports no domain app — enforced by the boundary checker.

        This pins the intent; `scripts/check_architecture_boundaries.py` is what
        actually keeps it true.
        """
        import apps.ml.services.inference as module

        source = module.__file__
        with open(source, encoding="utf-8") as fh:
            body = fh.read()

        for domain_app in ("annotations", "manuscripts", "scribes", "publications"):
            assert f"apps.{domain_app}" not in body


@pytest.mark.django_db
class TestTask:
    def test_the_task_delegates_and_returns_the_house_payload(self, enabled):
        job = InferenceService().submit(task="W1.1", provider="null", inputs={"a": 1})

        payload = run_inference.run(job.pk, {"a": 1}, {})

        assert payload == {"action": "inference", "job_id": job.pk, "status": MLJob.Status.SUCCEEDED}


def _registration(*, factory, hosted=False):
    from apps.ml.providers.registry import ProviderRegistration

    return ProviderRegistration(name="null", factory=factory, hosted=hosted)


def _hosted_registration():
    from apps.ml.providers.null import NullProvider
    from apps.ml.providers.registry import ProviderRegistration

    return ProviderRegistration(name="hosted-thing", factory=NullProvider, hosted=True)

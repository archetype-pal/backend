"""The circuit breaker — W0.1 / C2.

The commitment is that the ledger *drives* the cap rather than reporting it, so
these tests check the cap is computed from ledger rows and refuses before any
provider is reached.
"""

from datetime import timedelta

from django.utils import timezone
import pytest

from apps.ml.models import MLJob
from apps.ml.services import budget

from .factories import MLJobFactory


@pytest.mark.django_db
class TestKillSwitch:
    def test_inference_is_off_by_default(self, settings):
        """The app ships inert — nothing runs until someone turns it on."""
        assert settings.ML_INFERENCE_ENABLED is False

        with pytest.raises(budget.BudgetExceeded, match="disabled"):
            budget.check(task="W1.1")

    def test_enabling_it_allows_a_call_through(self, settings):
        settings.ML_INFERENCE_ENABLED = True

        budget.check(task="W1.1")


@pytest.mark.django_db
class TestSpendCaps:
    @pytest.fixture(autouse=True)
    def _enabled(self, settings):
        settings.ML_INFERENCE_ENABLED = True
        settings.ML_DAILY_COST_CAP_MICROS = 0
        settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0

    def test_a_zero_cap_disables_that_cap(self, settings):
        MLJobFactory(cost_micros=10**9)

        budget.check(task="W1.1")

    def test_the_total_cap_is_summed_from_the_ledger(self, settings):
        settings.ML_DAILY_COST_CAP_MICROS = 1000
        MLJobFactory(cost_micros=600)
        MLJobFactory(cost_micros=500)

        with pytest.raises(budget.BudgetExceeded, match="Daily spend cap"):
            budget.check(task="W1.1")

    def test_spend_below_the_cap_passes(self, settings):
        settings.ML_DAILY_COST_CAP_MICROS = 1000
        MLJobFactory(cost_micros=999)

        budget.check(task="W1.1")

    def test_spend_outside_the_window_does_not_count(self, settings):
        settings.ML_DAILY_COST_CAP_MICROS = 1000
        stale = MLJobFactory(cost_micros=5000)
        MLJob.objects.filter(pk=stale.pk).update(created=timezone.now() - timedelta(hours=25))

        budget.check(task="W1.1")

    def test_the_per_actor_cap_is_scoped_to_that_actor(self, settings, django_user_model):
        settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 100
        spender = django_user_model.objects.create_user(username="spender", password="x")
        other = django_user_model.objects.create_user(username="other", password="x")
        MLJobFactory(actor=spender, cost_micros=150)

        with pytest.raises(budget.BudgetExceeded, match="Per-actor"):
            budget.check(task="W1.1", actor_id=spender.pk)

        budget.check(task="W1.1", actor_id=other.pk)


@pytest.mark.django_db
class TestSpendSince:
    def test_scopes_by_task(self):
        MLJobFactory(task="W1.1", cost_micros=100)
        MLJobFactory(task="W1.2", cost_micros=200)

        assert budget.spend_since(task="W1.1") == 100
        assert budget.spend_since() == 300

    def test_is_zero_with_no_rows(self):
        assert budget.spend_since() == 0

"""The circuit breaker.

The programme's cost commitment is that the ledger *drives* a spend cap rather
than merely reporting spend. That distinction is this module: caps are computed
from the same rows the ledger already writes, and are checked before dispatch,
so an unbounded loop is refused rather than discovered on an invoice.

A refusal is itself written to the ledger (`MLJob.Status.REFUSED`) — spend caps
whose refusals are invisible cannot be audited.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from ..models import MLJob

# The window every cap is measured over. A rolling 24 hours rather than a
# calendar day: a runaway that starts at 23:00 must not get a fresh allowance
# an hour later.
WINDOW = timedelta(hours=24)
WINDOW_LABEL = "24h"


class BudgetExceeded(Exception):
    """A cap would be breached, or inference is switched off entirely."""


def _cap(name: str, default: int = 0) -> int:
    return int(getattr(settings, name, default))


def spend_since(*, actor_id: int | None = None, task: str = "") -> int:
    """Total `cost_micros` over the trailing window, optionally scoped."""
    queryset = MLJob.objects.filter(created__gte=timezone.now() - WINDOW)
    if actor_id is not None:
        queryset = queryset.filter(actor_id=actor_id)
    if task:
        queryset = queryset.filter(task=task)
    return int(queryset.aggregate(total=Sum("cost_micros"))["total"] or 0)


def check(*, task: str, actor_id: int | None = None) -> None:
    """Raise :class:`BudgetExceeded` if this call must not proceed.

    Checked before a provider is resolved, so a refusal costs nothing.
    """
    if not getattr(settings, "ML_INFERENCE_ENABLED", False):
        raise BudgetExceeded("Inference is disabled (ML_INFERENCE_ENABLED is off).")

    total_cap = _cap("ML_DAILY_COST_CAP_MICROS")
    if total_cap and spend_since() >= total_cap:
        raise BudgetExceeded(f"Daily spend cap reached ({total_cap} micros over {WINDOW_LABEL}).")

    actor_cap = _cap("ML_DAILY_COST_CAP_MICROS_PER_ACTOR")
    if actor_cap and actor_id is not None and spend_since(actor_id=actor_id) >= actor_cap:
        raise BudgetExceeded(f"Per-actor daily spend cap reached ({actor_cap} micros over {WINDOW_LABEL}).")

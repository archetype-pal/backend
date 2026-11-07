"""The circuit breaker.

The programme's cost commitment is that the ledger *drives* a spend cap rather
than merely reporting spend. That distinction is this module: caps are computed
from the same rows the ledger already writes, and are checked before dispatch,
so an unbounded loop is refused rather than discovered on an invoice.

A refusal is itself written to the ledger (`MLJob.Status.REFUSED`) — spend caps
whose refusals are invisible cannot be audited.
"""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from ..models import MLJob

# The window every cap is measured over. A rolling 24 hours rather than a
# calendar day: a runaway that starts at 23:00 must not get a fresh allowance
# an hour later.
WINDOW = timedelta(hours=24)
WINDOW_LABEL = "24h"


class BudgetExceeded(Exception):
    """A cap would be breached, or inference is switched off entirely.

    `str()` is for the ledger and names settings and sums, so it is not for
    showing to the person who asked.
    """


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


def check(*, task: str, actor_id: int | None = None, hosted: bool = True) -> None:
    """Raise :class:`BudgetExceeded` if this call must not proceed.

    Checked before a provider is resolved, so a refusal costs nothing. The caps
    are on money, so a self-hosted model, which bills nothing, passes them.
    """
    if not getattr(settings, "ML_INFERENCE_ENABLED", False):
        raise BudgetExceeded("Inference is disabled (ML_INFERENCE_ENABLED is off).")
    if not hosted:
        return

    total_cap = _cap("ML_DAILY_COST_CAP_MICROS")
    if total_cap and spend_since() >= total_cap:
        raise BudgetExceeded(f"Daily spend cap reached ({total_cap} micros over {WINDOW_LABEL}).")

    actor_cap = _cap("ML_DAILY_COST_CAP_MICROS_PER_ACTOR")
    if actor_cap and actor_id is not None and spend_since(actor_id=actor_id) >= actor_cap:
        raise BudgetExceeded(f"Per-actor daily spend cap reached ({actor_cap} micros over {WINDOW_LABEL}).")


def overview() -> dict[str, Any]:
    """The breaker's state, as an operator reads it.

    Whether inference may run at all, what the trailing window has spent
    against each cap, and how the window's calls ended, refusals included: a
    cap whose refusals cannot be seen is not auditable. `tasks` lists every
    task the ledger has seen, with its count, for filtering it.

    Caps are summed in micros whatever the currency, as `check` sums them, so
    `currencies` names what the window's costs were in; more than one means
    the cap is adding unlike amounts.
    """
    window = MLJob.objects.filter(created__gte=timezone.now() - WINDOW).order_by()
    by_status = dict.fromkeys(MLJob.Status.values, 0)
    for row in window.values("status").annotate(n=Count("id")):
        by_status[row["status"]] = row["n"]
    currencies = sorted(set(window.exclude(cost_currency="").values_list("cost_currency", flat=True)))
    tasks = [
        {"task": row["task"], "count": row["count"]}
        for row in MLJob.objects.order_by("task").values("task").annotate(count=Count("id"))
    ]
    return {
        "inference_enabled": bool(getattr(settings, "ML_INFERENCE_ENABLED", False)),
        "hosted_providers_enabled": bool(getattr(settings, "ML_HOSTED_PROVIDERS_ENABLED", False)),
        "window": WINDOW_LABEL,
        "spend_micros": spend_since(),
        "cap_micros": _cap("ML_DAILY_COST_CAP_MICROS"),
        "per_actor_cap_micros": _cap("ML_DAILY_COST_CAP_MICROS_PER_ACTOR"),
        "currencies": currencies,
        "by_status": by_status,
        "tasks": tasks,
    }

"""What the review queue gets through, model by model, against annotating by hand.

The programme's claim for W1.1 is throughput: reviewing a model's letters
should make annotations faster than drawing them. Two things answer it.

**How often a model is right**, from the queue's own record. A proposal is
accepted as filed, accepted after a correction, rejected or still pending, and
the ledger row that produced it names the model and its version. A proposal
accepted only after its letter or box was corrected counts against the model:
the reviewer did the work. These are counted over the proposals filed in the
window.

**How long a person spends on each.** Nothing records how long someone looked
at a proposal, so time is read from the gaps between a person's consecutive
actions: their decisions in the queue, and the annotations they created by
hand (from the audit trail). A gap of at most `SESSION_GAP` is time spent on
the action that ends it; a longer one is a break, and the action after it is
not timed. Decisions and hand annotations share one timeline per person, so no
minute is counted twice, and every action in the window is on it, whenever the
proposal it decided was filed. The same measure applied to both is what makes
"seconds per accepted letter" comparable with "seconds per letter drawn by
hand".
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from apps.annotations.models import GraphProposal
from apps.common.models import EditEvent

SESSION_GAP = timedelta(minutes=10)


@dataclass
class _Timed:
    """The working time ended by one kind of action."""

    actions: int = 0
    timed: int = 0
    gaps: list[float] = field(default_factory=list)

    def add(self, gap: float | None) -> None:
        self.actions += 1
        if gap is not None:
            self.timed += 1
            self.gaps.append(gap)

    def summary(self) -> dict[str, Any]:
        seconds = sum(self.gaps)
        return {
            "actions": self.actions,
            "timed": self.timed,
            "seconds": round(seconds, 1),
            "mean_seconds": round(seconds / self.timed, 1) if self.timed else None,
            "median_seconds": round(median(self.gaps), 1) if self.gaps else None,
        }


def _model_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        row["ml_job__task"] or "",
        row["ml_job__provider"] or "",
        row["ml_job__model_name"] or "",
        row["ml_job__model_version"] or "",
    )


def report(*, since: datetime, until: datetime) -> dict[str, Any]:
    """Acceptance and time per decision for each model, and the time per hand-made annotation."""
    rows = list(
        GraphProposal.objects.filter(created__gte=since, created__lt=until).values(
            "status",
            "allograph_id",
            "hand_id",
            "annotation",
            "proposed",
            "ml_job__task",
            "ml_job__provider",
            "ml_job__model_name",
            "ml_job__model_version",
        )
    )

    counts: dict[tuple[str, str, str, str], dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(
            (
                "filed",
                "pending",
                "accepted_as_filed",
                "accepted_corrected",
                "rejected",
                "corrected_letter",
                "corrected_box",
                "corrected_hand",
            ),
            0,
        )
    )
    for row in rows:
        key = _model_key(row)
        tally = counts[key]
        tally["filed"] += 1
        filed = row["proposed"]
        # The hand is not the model's: it is the page's first, by convention.
        missed = filed is not None and (
            filed.get("allograph") != row["allograph_id"] or filed.get("annotation") != row["annotation"]
        )
        if filed is not None:
            tally["corrected_letter"] += filed.get("allograph") != row["allograph_id"]
            tally["corrected_hand"] += filed.get("hand") != row["hand_id"]
            tally["corrected_box"] += filed.get("annotation") != row["annotation"]
        if row["status"] == GraphProposal.Status.PENDING:
            tally["pending"] += 1
        elif row["status"] == GraphProposal.Status.REJECTED:
            tally["rejected"] += 1
        else:
            tally["accepted_corrected" if missed else "accepted_as_filed"] += 1

    # (when, person, the model whose proposal was decided or None for an
    # annotation made by hand, whether it became an annotation)
    timeline: list[tuple[datetime, int, tuple[str, str, str, str] | None, bool]] = [
        (row["reviewed"], row["reviewer_id"], _model_key(row), row["status"] == GraphProposal.Status.ACCEPTED)
        for row in GraphProposal.objects.filter(reviewer__isnull=False, reviewed__gte=since, reviewed__lt=until).values(
            "reviewer_id",
            "reviewed",
            "status",
            "ml_job__task",
            "ml_job__provider",
            "ml_job__model_name",
            "ml_job__model_version",
        )
    ]

    # Annotations made by hand: every graph created in the window except those
    # an accept created, which the decisions above already account for.
    from_queue = set(
        GraphProposal.objects.filter(accepted_graph__isnull=False).values_list("accepted_graph_id", flat=True)
    )
    for actor_id, created, target_id in EditEvent.objects.filter(
        target_type="graph",
        action=EditEvent.Action.CREATED,
        actor__isnull=False,
        created__gte=since,
        created__lt=until,
    ).values_list("actor_id", "created", "target_id"):
        if target_id not in from_queue:
            timeline.append((created, actor_id, None, True))

    decided: dict[tuple[str, str, str, str], _Timed] = defaultdict(_Timed)
    decided_accepted: dict[tuple[str, str, str, str], int] = defaultdict(int)
    by_hand = _Timed()
    last_by_person: dict[int, datetime] = {}
    for when, person, model, became in sorted(timeline, key=lambda event: (event[1], event[0])):
        previous = last_by_person.get(person)
        last_by_person[person] = when
        gap = (when - previous).total_seconds() if previous is not None and when - previous <= SESSION_GAP else None
        if model is None:
            by_hand.add(gap)
            continue
        decided[model].add(gap)
        decided_accepted[model] += became

    hand = by_hand.summary()
    models = []
    for key in sorted(counts.keys() | decided.keys()):
        task, provider, model_name, model_version = key
        tally = counts[key]
        decisions = tally["accepted_as_filed"] + tally["accepted_corrected"] + tally["rejected"]
        accepted = tally["accepted_as_filed"] + tally["accepted_corrected"]
        timing = decided[key].summary()
        # Reviewing time per annotation the decisions in the window made,
        # rejections and corrections included; an untimed decision is taken to
        # cost the mean.
        per_accepted = (
            round(timing["mean_seconds"] * decided[key].actions / decided_accepted[key], 1)
            if decided_accepted[key] and timing["mean_seconds"] is not None
            else None
        )
        models.append(
            {
                "task": task,
                "provider": provider,
                "model_name": model_name,
                "model_version": model_version,
                **tally,
                "accepted": accepted,
                # Right as filed, of the proposals someone decided.
                "acceptance_rate": round(tally["accepted_as_filed"] / decisions, 3) if decisions else None,
                "accepted_rate": round(accepted / decisions, 3) if decisions else None,
                # The decisions made in the window, whenever the proposals were filed.
                "decision_time": {**timing, "accepted": decided_accepted[key]},
                "seconds_per_accepted": per_accepted,
                # How many times faster than drawing a letter by hand: W1.1's target is 5 to 10.
                "speedup": (
                    round(hand["mean_seconds"] / per_accepted, 2)
                    if per_accepted and hand["mean_seconds"] is not None
                    else None
                ),
            }
        )

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "session_gap_seconds": int(SESSION_GAP.total_seconds()),
        "models": models,
        "by_hand": hand,
    }

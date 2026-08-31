"""Recording an evaluation — and refusing to record an unusable one (W0.3).

"No model ships without numbers, and no number ships without its split and its
baseline" is a rule the programme states three times. This is where it is
enforced. `record_run` will not write a row that omits the release, the split or
the baseline, so a published score always arrives with the two things needed to
judge it: what it was measured on, and what it beat.

The refusal is the feature, in the same way the budget guard's and the write
gate's are. A rule that only exists in a document is a rule that gets skipped on
the afternoon before a deadline.
"""

from typing import Any, cast

from ..evaluation import Metrics
from ..models import EvaluationRun


class EvaluationError(Exception):
    """The run cannot be recorded as offered."""


def record_run(
    *,
    model_name: str,
    task: str,
    release: str,
    split: str,
    metrics: Metrics,
    baseline_name: str,
    baseline_metrics: Metrics,
    model_version: str = "",
    notes: str = "",
) -> EvaluationRun:
    """Record one held-out evaluation, or refuse and say what is missing."""
    if not release:
        raise EvaluationError(
            "An evaluation must name the release it ran against; a score on unnamed data cannot be reproduced."
        )
    if not split:
        raise EvaluationError(
            "An evaluation must name its split; a score whose held-out set is unknown is not a held-out score."
        )
    if not baseline_name or baseline_metrics is None:
        raise EvaluationError("An evaluation must carry a baseline; a number with no floor beside it is not a result.")
    if metrics.n != baseline_metrics.n:
        raise EvaluationError(
            f"Model and baseline were scored on different sets ({metrics.n} vs {baseline_metrics.n}); "
            "the comparison would be meaningless."
        )

    return cast(
        EvaluationRun,
        EvaluationRun.objects.create(
            model_name=model_name,
            model_version=model_version,
            task=task,
            release=release,
            split=split,
            metrics=metrics.as_dict(),
            baseline_name=baseline_name,
            baseline_metrics=baseline_metrics.as_dict(),
            notes=notes,
        ),
    )


def latest_per_model(task: str = "") -> list[dict[str, Any]]:
    """The most recent run for each model version, newest first."""
    queryset = EvaluationRun.objects.all()
    if task:
        queryset = queryset.filter(task=task)

    seen: set[tuple[str, str, str]] = set()
    rows: list[dict[str, Any]] = []
    for run in queryset:
        key = (run.model_name, run.model_version, run.task)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "model": f"{run.model_name}@{run.model_version or '?'}",
                "task": run.task,
                "release": run.release,
                "split": run.split,
                "accuracy": run.headline,
                "macro_f1": run.metrics.get("macro_f1"),
                "baseline": run.baseline_name,
                "baseline_accuracy": run.baseline_headline,
                "beats_baseline": run.beats_baseline,
                "created": run.created,
            }
        )
    return rows

"""Auditing the corpus's datings (AI programme W4.1 precondition).

`ROADMAP.md` records one charter whose header date is contradicted by its own
witness list, and notes that a corpus-wide audit is unscoped and unowned. This
is that audit, and it exists for two reasons.

The first is data quality: a dating that cannot be true is worth finding whether
or not a model ever reads it.

The second is that W4.1 proposes to learn date-from-script and report
disagreements as re-dating candidates. That is only honest if the training
labels were not themselves derived from the script — otherwise the model learns
the palaeographer's judgement and then "discovers" it. Selecting that
anti-circularity subset requires knowing how each dating was reached, which is
what `HistoricalItemDateAssessment` is for. It currently holds nothing, so the
subset cannot be selected at all: W4.1 is not merely unstarted, it is
unstartable until someone records provenance.
"""

from dataclasses import dataclass, field
import re

from apps.common.models import Date
from apps.manuscripts.models import HistoricalItem, HistoricalItemDateAssessment

# Generous bounds for a corpus of Scottish royal charters c.1100-1250. Anything
# outside this is a data-entry artefact rather than a scholarly claim.
PLAUSIBLE_EARLIEST = 1000
PLAUSIBLE_LATEST = 1400

# Years as written in a date label: 1000-1499, four digits.
_YEAR = re.compile(r"\b(1[0-4]\d{2})\b")


@dataclass
class Problem:
    date_id: int
    label: str
    min_weight: int | None
    max_weight: int | None
    kind: str
    detail: str


@dataclass
class Audit:
    dates: int = 0
    items: int = 0
    items_with_a_date: int = 0
    problems: list[Problem] = field(default_factory=list)
    provenance_recorded: int = 0

    @property
    def usable_for_training(self) -> int:
        """Datings a model could learn from: sound bounds, inside the era.

        Not the same as *trustworthy* — see `provenance_recorded`, which is the
        number that decides whether W4.1 can be done honestly at all.
        """
        unusable = {p.date_id for p in self.problems if p.kind in ("inverted", "unbounded", "out_of_era")}
        return self.dates - len(unusable)

    def by_kind(self, kind: str) -> list[Problem]:
        return [p for p in self.problems if p.kind == kind]


def run() -> Audit:
    """Audit every dating in the corpus. Read-only."""
    audit = Audit(
        dates=Date.objects.count(),
        items=HistoricalItem.objects.count(),
        items_with_a_date=HistoricalItem.objects.filter(date__isnull=False).count(),
        provenance_recorded=HistoricalItemDateAssessment.objects.count(),
    )

    for date_id, label, low, high in Date.objects.values_list("id", "date", "min_weight", "max_weight"):
        label = label or ""

        if low is None or high is None or low == 0 or high == 0:
            # A zero bound is not "year zero", it is "nobody filled this in" —
            # and it sorts to the front of every ordered query that uses it.
            audit.problems.append(
                Problem(date_id, label, low, high, "unbounded", "No usable numeric bound; sorts as year 0.")
            )
            continue

        if low > high:
            audit.problems.append(
                Problem(date_id, label, low, high, "inverted", f"Lower bound {low} is after upper bound {high}.")
            )
            continue

        if low < PLAUSIBLE_EARLIEST or high > PLAUSIBLE_LATEST:
            audit.problems.append(
                Problem(
                    date_id,
                    label,
                    low,
                    high,
                    "out_of_era",
                    f"Range {low}-{high} falls outside {PLAUSIBLE_EARLIEST}-{PLAUSIBLE_LATEST}.",
                )
            )
            continue

        years = [int(y) for y in _YEAR.findall(label)]
        if years and (min(years) < low or max(years) > high):
            # The label is what a scholar wrote; the bounds are what sorts and
            # what a model would train on. When they disagree the bounds are
            # usually the transcription error, and they are the half nobody reads.
            audit.problems.append(
                Problem(
                    date_id,
                    label,
                    low,
                    high,
                    "label_disagrees",
                    f"Label names {sorted(set(years))}, outside the recorded range {low}-{high}.",
                )
            )

    return audit

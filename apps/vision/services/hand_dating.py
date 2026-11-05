"""Dating a charter by the hands written most like it (AI programme W4.1).

Each compared hand is dated by the mean of the catalogue dates of its nearest
hands, as W1.3 compares them, never counting a hand on the same charter. The
guess is scored against the hand's own catalogue date, beside two that know
nothing of the script: the middle date of the other hands, and as many other
hands drawn at random. Comparing only with hands held in other repositories
tests whether the script dates the charter, and not the archive it is kept in
or the campaign that photographed it.

**Measured** with `eval_hand_dating` on the dev database of 2026-11-05, where
109 of the 110 compared hands are dated. Guessed from its five nearest dated
hands on other charters, a hand's date was off by 23.7 years on average
(median 17.5), against 30.6 for always guessing the middle date and 31.7 for
five hands at random; 43% of the guesses fell within ten years of the
catalogue's range. From hands held in other repositories only: 25.6, against
34.0 and 33.4. `trocr`'s vectors did better on other charters (20.5, with 52%
within ten years) but no better from other repositories (24.1), so some of
their edge is the archive's. A linear model from each glyph's form to its
charter's date did no better than the neighbours.

So the script carries a date, but a coarse one, and the guesses are pulled
towards the middle: the worst are the oldest and newest charters, several of
the 1120s to 1140s coming out around 1200 and several of the 1240s around
1165. Nothing is stored and no route serves it: a guess this rough does not
belong beside a catalogue's date, and its largest disagreements with the
catalogue are the pull to the middle, not errors to flag.
"""

from dataclasses import dataclass
import random
import statistics

import numpy as np

from .hand_similarity import Comparison

# The nearest dated hands a guess is the mean of.
NEIGHBOURS = 5
# Years either side of the catalogue's range a guess may fall and still count as within it.
SLACK = 10
# Random draws the by-chance error is averaged over.
DRAWS = 200


@dataclass(frozen=True)
class Dated:
    """A hand's charter, as the catalogue dates it and where it is held."""

    low: int
    high: int
    charter: int
    repository: int | None

    @property
    def middle(self) -> float:
        return (self.low + self.high) / 2


def catalogue_dates(hand_ids: list[int]) -> dict[int, Dated]:
    """Each hand's charter date. A date with no year (its weights not above 0) is no date."""
    from apps.scribes.models import Hand

    rows = Hand.objects.filter(pk__in=hand_ids, item_part__historical_item__date__min_weight__gt=0).values_list(
        "pk",
        "item_part__historical_item__date__min_weight",
        "item_part__historical_item__date__max_weight",
        "item_part__historical_item_id",
        "item_part__current_item__repository_id",
    )
    return {
        hand: Dated(low=low, high=high, charter=charter, repository=repository)
        for hand, low, high, charter, repository in rows
    }


@dataclass
class DatingScore:
    """How near the dates of a hand's nearest hands come to its own, beside guesses that ignore the script."""

    hands: int  # dated hands that had a dated neighbour to be guessed from
    neighbours: int
    other_repositories: bool
    error: float  # mean absolute, in years
    median_error: float
    within: int  # guesses within the catalogue's range, give or take SLACK years
    correlation: float  # between the guesses and the catalogue's middle dates
    middle_error: float  # always guessing the middle date of the other hands
    random_error: float  # the mean of as many other hands drawn at random


def score_dating(
    comparison: Comparison,
    dates: dict[int, Dated],
    *,
    neighbours: int = NEIGHBOURS,
    other_repositories: bool = False,
    seed: int = 1,
) -> DatingScore | None:
    """Guess each dated hand's date from its nearest dated hands, and score the guesses. None if none can be."""
    hands = comparison.hands
    dated = [index for index, hand in enumerate(hands) if hand in dates]

    def allowed(i: int, j: int) -> bool:
        mine, theirs = dates[hands[i]], dates[hands[j]]
        if theirs.charter == mine.charter:
            return False
        return not (other_repositories and theirs.repository == mine.repository)

    rng = random.Random(seed)
    guesses, truths, middle_errors, pools = [], [], [], []
    within = 0
    for i in dated:
        # A hand is on its own charter, so `allowed` leaves it out too.
        others = [j for j in dated if allowed(i, j)]
        comparable = [j for j in comparison.nearest(i, count=len(hands)) if j in set(others)]
        if not comparable:
            continue
        own = dates[hands[i]]
        guess = float(np.mean([dates[hands[j]].middle for j in comparable[:neighbours]]))
        guesses.append(guess)
        truths.append(own.middle)
        within += own.low - SLACK <= guess <= own.high + SLACK
        middle_errors.append(abs(statistics.median(dates[hands[j]].middle for j in others) - own.middle))
        pools.append((own.middle, comparable))
    if not guesses:
        return None

    errors = np.abs(np.array(guesses) - np.array(truths))
    random_errors = [
        np.mean(
            [
                abs(np.mean([dates[hands[j]].middle for j in rng.sample(pool, min(neighbours, len(pool)))]) - truth)
                for truth, pool in pools
            ]
        )
        for _ in range(DRAWS)
    ]
    spread = np.std(guesses) * np.std(truths)
    return DatingScore(
        hands=len(guesses),
        neighbours=neighbours,
        other_repositories=other_repositories,
        error=float(errors.mean()),
        median_error=float(np.median(errors)),
        within=within,
        correlation=float(np.corrcoef(guesses, truths)[0, 1]) if spread > 0 else 0.0,
        middle_error=float(np.mean(middle_errors)),
        random_error=float(np.mean(random_errors)),
    )

"""Dating a charter by the hands written most like it (W4.1).

The comparisons are written out by hand, so every guess and every baseline can
be worked out on paper.
"""

from io import StringIO

from django.core.management import CommandError, call_command
import numpy as np
import pytest

from apps.common.tests.factories import DateFactory
from apps.manuscripts.tests.factories import ItemPartFactory
from apps.scribes.tests.factories import HandFactory
from apps.vision.services import hand_dating, hand_similarity
from apps.vision.services.hand_dating import Dated
from apps.vision.services.hand_similarity import Comparison

NO = -np.inf


def _comparison(hands: list[int], similarity: list[list[float]]) -> Comparison:
    return Comparison(vectors="hog@test-1", hands=hands, glyphs={}, similarity=np.array(similarity, dtype=float))


# Four hands on four charters, two in each of two repositories: an early pair and a late pair,
# each hand most like its pair's other hand, then like the other pair.
FOUR = _comparison(
    [10, 20, 30, 40],
    [
        [NO, 0.9, 0.5, 0.4],
        [0.9, NO, 0.3, 0.2],
        [0.5, 0.3, NO, 0.8],
        [0.4, 0.2, 0.8, NO],
    ],
)
DATES = {
    10: Dated(low=1100, high=1100, charter=1, repository=1),
    20: Dated(low=1110, high=1120, charter=2, repository=1),
    30: Dated(low=1200, high=1200, charter=3, repository=2),
    40: Dated(low=1210, high=1230, charter=4, repository=2),
}


class TestScoreDating:
    def test_guesses_each_hand_s_date_from_its_nearest_and_scores_it_beside_guesses_blind_to_the_script(self):
        score = hand_dating.score_dating(FOUR, DATES, neighbours=1)

        # Guesses 1115, 1100, 1220, 1200 for 1100, 1115, 1200, 1220: off by 15, 15, 20, 20.
        assert (score.hands, score.neighbours, score.other_repositories) == (4, 1, False)
        assert (score.error, score.median_error) == (17.5, 17.5)
        # Within ten years of 1100-1100, 1110-1120, 1200-1200, 1210-1230: the second and fourth.
        assert score.within == 2
        assert score.correlation == pytest.approx(np.corrcoef([1115, 1100, 1220, 1200], [1100, 1115, 1200, 1220])[0, 1])
        # The other three hands' middle date: 1200, 1200, 1115, 1115.
        assert score.middle_error == pytest.approx((100 + 85 + 85 + 105) / 4)
        # One other hand at random: on average (15+100+120 + 15+85+105 + 100+85+20 + 120+105+20) / 12.
        assert score.random_error == pytest.approx(890 / 12, abs=4)

    def test_a_guess_is_the_mean_of_the_nearest_dated_hands_however_many_are_asked_for(self):
        score = hand_dating.score_dating(FOUR, {hand: DATES[hand] for hand in (10, 20, 30)}, neighbours=2)

        # 10 from 20 and 30: 1157.5; 20 from 10 and 30: 1150; 30 from 10 and 20: 1107.5. Hand 40 is undated.
        assert score.hands == 3
        assert score.error == pytest.approx((57.5 + 35 + 92.5) / 3)
        # Two hands at random are both of the other two, so chance guesses the same.
        assert score.random_error == pytest.approx(score.error)

    def test_a_guess_is_the_mean_not_the_middle_of_its_neighbours_and_asks_for_no_more_than_there_are(self):
        three = hand_dating.score_dating(FOUR, DATES, neighbours=3)

        # 10 from 20, 30 and 40: 1178.33, not their middle 1200. Asking for five uses the three there are.
        assert three.error == pytest.approx((78.33 + 58.33 + 55 + 81.67) / 4, abs=0.01)
        assert hand_dating.score_dating(FOUR, DATES, neighbours=5).error == three.error

    def test_a_guess_within_ten_years_of_either_end_of_the_range_counts_as_within_it(self):
        comparison = _comparison([10, 20, 30], [[NO, 0.9, 0.1], [0.9, NO, 0.1], [0.1, 0.9, NO]])
        dates = {
            10: Dated(low=1100, high=1150, charter=1, repository=1),  # guessed 1158, from 20
            20: Dated(low=1158, high=1158, charter=2, repository=1),  # guessed 1125, from 10
            30: Dated(low=1300, high=1300, charter=3, repository=1),  # guessed 1158, from 20
        }

        assert hand_dating.score_dating(comparison, dates, neighbours=1).within == 1

    def test_a_hand_on_the_same_charter_is_never_a_neighbour(self):
        comparison = _comparison([10, 20, 30], [[NO, 0.9, 0.1], [0.9, NO, 0.1], [0.1, 0.1, NO]])
        dates = {
            10: Dated(low=1100, high=1100, charter=1, repository=1),
            20: Dated(low=1100, high=1100, charter=1, repository=1),  # the same charter's dorse, say
            30: Dated(low=1200, high=1200, charter=2, repository=1),
        }

        score = hand_dating.score_dating(comparison, dates, neighbours=1)

        # 10 and 20 are guessed from 30 alone; 30 from the nearer of the two, 10.
        assert score.error == pytest.approx((100 + 100 + 100) / 3)
        # Nor counts towards the middle date: 10's is 30's, 1200.
        assert score.middle_error == pytest.approx((100 + 100 + 100) / 3)

    def test_from_other_repositories_only_the_nearest_held_elsewhere_count(self):
        score = hand_dating.score_dating(FOUR, DATES, neighbours=1, other_repositories=True)

        # 10 from 30, 20 from 30, 30 from 10, 40 from 10: off by 100, 85, 100, 120.
        assert score.other_repositories is True
        assert score.error == pytest.approx((100 + 85 + 100 + 120) / 4)
        assert score.median_error == 100
        # The middle date of the other repository's two hands: 1210, 1210, 1107.5, 1107.5.
        assert score.middle_error == pytest.approx((110 + 95 + 92.5 + 112.5) / 4)

    def test_a_hand_compared_with_no_dated_hand_is_not_guessed(self):
        comparison = _comparison([10, 20, 30], [[NO, 0.9, NO], [0.9, NO, NO], [NO, NO, NO]])
        dates = {hand: DATES[hand] for hand in (10, 20)} | {30: DATES[30]}

        score = hand_dating.score_dating(comparison, dates, neighbours=1)

        # Hand 30 shares too few letters with either to be compared, so it is neither guessed nor a guess.
        assert score.hands == 2
        assert score.error == 15
        # Nor can chance pick it: each hand's only comparable hand is the other.
        assert score.random_error == 15
        # The blind guess still knows 30's date: 10's is the middle of 20's and 30's, 1157.5;
        # 20's, of 10's and 30's, 1150.
        assert score.middle_error == pytest.approx((57.5 + 35) / 2)

    def test_nothing_to_score_is_none(self):
        assert hand_dating.score_dating(FOUR, {}) is None
        assert hand_dating.score_dating(FOUR, {10: DATES[10]}) is None

    def test_guesses_all_alike_have_no_correlation(self):
        comparison = _comparison([10, 20, 30], [[NO, 0.9, 0.1], [0.1, NO, 0.9], [0.9, 0.1, NO]])
        dates = {
            10: Dated(low=1150, high=1150, charter=1, repository=1),
            20: Dated(low=1150, high=1150, charter=2, repository=1),
            30: Dated(low=1150, high=1150, charter=3, repository=1),
        }

        assert hand_dating.score_dating(comparison, dates, neighbours=1).correlation == 0.0

    def test_the_same_seed_draws_the_same_random_hands(self):
        first = hand_dating.score_dating(FOUR, DATES, neighbours=1, seed=5).random_error

        assert hand_dating.score_dating(FOUR, DATES, neighbours=1, seed=5).random_error == first
        assert any(
            hand_dating.score_dating(FOUR, DATES, neighbours=1, seed=seed).random_error != first for seed in range(6, 9)
        )


@pytest.mark.django_db
class TestCatalogueDates:
    def test_reads_each_hand_s_charter_date_and_repository_and_leaves_out_a_date_with_no_year(self):
        dated = HandFactory(
            item_part=ItemPartFactory(historical_item__date=DateFactory(min_weight=1165, max_weight=1177))
        )
        yearless = HandFactory(item_part=ItemPartFactory(historical_item__date=DateFactory(min_weight=0, max_weight=0)))
        undated = HandFactory(item_part=ItemPartFactory(historical_item__date=None))
        elsewhere = HandFactory()

        dates = hand_dating.catalogue_dates([dated.pk, yearless.pk, undated.pk])

        part = dated.item_part
        assert dates == {
            dated.pk: Dated(
                low=1165, high=1177, charter=part.historical_item_id, repository=part.current_item.repository_id
            )
        }
        assert dates[dated.pk].middle == 1171
        assert elsewhere.pk not in dates


class TestCommand:
    def test_reports_the_guesses_on_other_charters_and_from_other_repositories(self, monkeypatch):
        monkeypatch.setattr(hand_similarity, "compare", lambda part: FOUR)
        monkeypatch.setattr(hand_dating, "catalogue_dates", lambda hands: DATES)
        out = StringIO()

        call_command("eval_hand_dating", "--neighbours", "1", stdout=out)

        lines = out.getvalue().splitlines()
        assert lines[0] == "hog@test-1: 4 hands compared, 4 of them dated; each guessed from its 1 nearest dated hands"
        assert lines[1].startswith(
            "  on other charters, 4 hands: off by 17.5 years on average (median 17.5), 2 (50%) within 10 years "
            "of the catalogue's range, correlation "
        )
        assert "the middle date is off by 93.8, as many hands at random by " in lines[1]
        assert lines[2].startswith("  held in other repositories, 4 hands: off by 101.2 years on average")

    def test_says_when_there_is_nothing_to_score(self, monkeypatch):
        monkeypatch.setattr(hand_similarity, "compare", lambda part: FOUR)
        monkeypatch.setattr(hand_dating, "catalogue_dates", lambda hands: {})
        out = StringIO()

        call_command("eval_hand_dating", stdout=out)

        assert out.getvalue().splitlines()[1:] == [
            "  on other charters: no dated hand has a dated hand to compare with; nothing to score",
            "  held in other repositories: no dated hand has a dated hand to compare with; nothing to score",
        ]

    def test_compares_by_the_encoder_asked_for(self, monkeypatch):
        asked = []
        monkeypatch.setattr(hand_similarity, "part_for", lambda encoder: asked.append(encoder) or "trocr part")
        monkeypatch.setattr(hand_similarity, "compare", lambda part: asked.append(part) or FOUR)
        monkeypatch.setattr(hand_dating, "catalogue_dates", lambda hands: DATES)

        call_command("eval_hand_dating", "--encoder", "trocr", stdout=StringIO())

        assert asked == ["trocr", "trocr part"]

    def test_refuses_no_neighbours_or_an_encoder_it_cannot_compare_by(self, monkeypatch):
        def part_for(encoder):
            raise ValueError(f"No stored vectors from {encoder}.")

        monkeypatch.setattr(hand_similarity, "part_for", part_for)

        with pytest.raises(CommandError, match="at least 1"):
            call_command("eval_hand_dating", "--neighbours", "0")
        with pytest.raises(CommandError, match="No stored vectors from ink"):
            call_command("eval_hand_dating", "--encoder", "ink")

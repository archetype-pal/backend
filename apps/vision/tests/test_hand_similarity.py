"""Hands whose letters are alike (W1.3).

The vectors are tiny and the thresholds lowered, so each comparison can be
worked out by hand; one test checks the vectorised arithmetic against a plain
loop on random vectors.
"""

from collections import defaultdict
from io import StringIO

from django.core.management import CommandError, call_command
import numpy as np
import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphFactory
from apps.scribes.models import Scribe
from apps.scribes.tests.factories import HandFactory, ScribeFactory
from apps.symbols_structure.tests.factories import AllographFactory
from apps.vision.models import GlyphEmbedding, HandSimilarity
from apps.vision.services import hand_similarity
from apps.vision.services.glyph_search import Part

pytestmark = pytest.mark.django_db

TINY = Part("hog", "test-1", 2)


@pytest.fixture(autouse=True)
def tiny(monkeypatch):
    monkeypatch.setattr(hand_similarity, "PART", TINY)
    monkeypatch.setattr(hand_similarity, "MIN_GLYPHS", 2)
    monkeypatch.setattr(hand_similarity, "MIN_SHARED", 2)


def _glyph(hand, allograph, vector, *, part: Part = TINY, current: bool = True) -> Graph:
    graph = GraphFactory(hand=hand, allograph=allograph)
    GlyphEmbedding.objects.create(
        graph=graph,
        encoder=part.encoder,
        model_name=part.encoder,
        model_version=part.model_version,
        dimensions=len(vector),
        vector=GlyphEmbedding.pack(vector),
        crop_digest=GlyphEmbedding.crop_digest_for(graph) if current else "",
    )
    return graph


def _similarity(comparison: hand_similarity.Comparison, a, b) -> float:
    return float(comparison.similarity[comparison.hands.index(a.pk), comparison.hands.index(b.pk)])


class TestCompare:
    def test_two_hands_that_write_their_shared_letters_alike_are_alike_whatever_else_they_write(self):
        a, b, c = AllographFactory.create_batch(3)
        x, y, z = HandFactory.create_batch(3)
        for hand, form_a, form_b in ((x, [1, 0], [0, 1]), (y, [1, 0], [0, 1]), (z, [0, 1], [1, 0])):
            _glyph(hand, a, form_a)
            _glyph(hand, b, form_b)
        for _ in range(5):
            _glyph(x, c, [1, 1])

        comparison = hand_similarity.compare()

        assert _similarity(comparison, x, y) == pytest.approx(1.0)
        assert _similarity(comparison, x, z) == pytest.approx(-1.0)

    def test_is_the_count_weighted_mean_of_the_cosines_of_centred_letter_means(self, monkeypatch):
        monkeypatch.setattr(hand_similarity, "PART", Part("hog", "test-1", 4))
        rng = np.random.default_rng(3)
        hands = HandFactory.create_batch(4)
        allographs = AllographFactory.create_batch(3)
        written = defaultdict(list)
        for hand in hands:
            for allograph in allographs:
                for _ in range(int(rng.integers(1, 4))):
                    vector = rng.normal(size=4)
                    _glyph(hand, allograph, list(vector), part=hand_similarity.PART)
                    written[(hand.pk, allograph.pk)].append(vector / np.linalg.norm(vector))

        comparison = hand_similarity.compare()

        def unit(v):
            return v / np.linalg.norm(v)

        usual = {
            allograph.pk: np.mean([v for (_, a), vs in written.items() if a == allograph.pk for v in vs], axis=0)
            for allograph in allographs
        }
        for first in hands:
            for second in hands:
                if first == second:
                    continue
                total = weight = 0.0
                for allograph in allographs:
                    mine = written[(first.pk, allograph.pk)]
                    theirs = written[(second.pk, allograph.pk)]
                    cosine = unit(np.mean(mine, axis=0) - usual[allograph.pk]) @ unit(
                        np.mean(theirs, axis=0) - usual[allograph.pk]
                    )
                    w = min(len(mine), len(theirs))
                    total += w * cosine
                    weight += w
                assert _similarity(comparison, first, second) == pytest.approx(total / weight, abs=1e-6)

    def test_a_hand_with_too_few_glyphs_is_not_compared_but_still_shapes_the_usual_form(self):
        a, b = AllographFactory.create_batch(2)
        x, y, sparse = HandFactory.create_batch(3)
        for hand in (x, y):
            _glyph(hand, a, [1, 0])
            _glyph(hand, b, [0, 1])
        _glyph(sparse, a, [0, 1])

        comparison = hand_similarity.compare()

        assert comparison.hands == sorted([x.pk, y.pk])
        assert comparison.glyphs == {x.pk: 2, y.pk: 2, sparse.pk: 1}
        # Without the sparse hand's a, x and y's a's would be the usual a, and centring would leave nothing.
        assert comparison.letters_between(0, 1)[0]["similarity"] == pytest.approx(1.0)

    def test_two_hands_sharing_too_few_letters_are_not_compared(self):
        a, b, c = AllographFactory.create_batch(3)
        x, y = HandFactory.create_batch(2)
        _glyph(x, a, [1, 0])
        _glyph(x, b, [0, 1])
        _glyph(y, a, [1, 0])
        _glyph(y, c, [0, 1])

        comparison = hand_similarity.compare()

        assert comparison.similarity[0, 1] == -np.inf
        assert comparison.nearest(0) == []

    def test_leaves_out_stale_trashed_and_other_vectors(self):
        a, b = AllographFactory.create_batch(2)
        x, y = HandFactory.create_batch(2)
        for hand in (x, y):
            _glyph(hand, a, [1, 0])
            _glyph(hand, b, [0, 1])
        _glyph(x, a, [5, 5], current=False)
        _glyph(x, b, [5, 5]).soft_delete()
        _glyph(x, a, [5, 5], part=Part("hog", "other-weights", 2))
        _glyph(x, a, [5, 5], part=Part("ink", TINY.model_version, 2))

        assert hand_similarity.compare().glyphs == {x.pk: 2, y.pk: 2}

    def test_nearest_and_the_letters_between_two_hands(self):
        a, b, c = AllographFactory.create_batch(3)
        x, near, far = HandFactory.create_batch(3)
        for hand, forms in ((x, ([1, 0], [0, 1])), (near, ([1, 0.2], [0.1, 1])), (far, ([0, 1], [1, 0]))):
            _glyph(hand, a, forms[0])
            _glyph(hand, b, forms[1])
        _glyph(x, b, [0, 1])
        _glyph(near, b, [0, 1])
        _glyph(far, c, [1, 1])

        comparison = hand_similarity.compare()
        i, j = comparison.hands.index(x.pk), comparison.hands.index(near.pk)

        assert [comparison.hands[k] for k in comparison.nearest(i)] == [near.pk, far.pk]
        letters = comparison.letters_between(i, j)
        assert [entry["allograph"] for entry in letters] == [b.pk, a.pk]
        assert letters[0]["glyphs"] == [2, 2]
        assert letters[1]["glyphs"] == [1, 1]


class TestCompareHands:
    def _three_hands(self):
        a, b = AllographFactory.create_batch(2)
        hands = HandFactory.create_batch(3)
        for hand, forms in zip(hands, (([1, 0], [0, 1]), ([1, 0.1], [0, 1]), ([0, 1], [1, 0])), strict=True):
            _glyph(hand, a, forms[0])
            _glyph(hand, b, forms[1])
        return hands

    def test_stores_each_hand_s_nearest_ranked_from_one_on_both_sides(self):
        x, y, z = self._three_hands()

        tally = hand_similarity.compare_hands()

        assert (tally.compared, tally.too_few_glyphs, tally.stored) == (3, 0, 6)
        stored = {(row.hand_id, row.rank): row.other_id for row in HandSimilarity.objects.all()}
        assert stored[(x.pk, 1)] == y.pk
        assert stored[(y.pk, 1)] == x.pk
        assert stored[(z.pk, 2)] in {x.pk, y.pk}
        row = HandSimilarity.objects.get(hand=x, other=y)
        assert row.vectors == "hog@test-1"
        assert {entry["allograph"] for entry in row.letters} == set(Graph.objects.values_list("allograph", flat=True))

    def test_replaces_what_was_stored_before(self):
        x, y, z = self._three_hands()
        hand_similarity.compare_hands()
        for graph in Graph.objects.filter(hand=z):
            graph.soft_delete()

        hand_similarity.compare_hands(nearest=1)

        assert sorted(HandSimilarity.objects.values_list("hand_id", "other_id", "rank")) == sorted(
            [(x.pk, y.pk, 1), (y.pk, x.pk, 1)]
        )

    def test_the_command_says_what_it_did(self):
        self._three_hands()
        out = StringIO()

        call_command("compare_hands", stdout=out)

        assert "Compared 3 hands; 0 had fewer than 2 glyphs" in out.getvalue()
        assert "Stored 6 nearest hands" in out.getvalue()


class TestScoreAttributions:
    def _hands(self, scribe, forms_a, forms_b, a, b):
        hand = HandFactory(scribe=scribe)
        _glyph(hand, a, forms_a)
        _glyph(hand, b, forms_b)
        return hand

    def test_counts_a_scribe_s_other_hands_among_each_hand_s_nearest(self):
        a, b = AllographFactory.create_batch(2)
        scribe = ScribeFactory()
        placeholder = ScribeFactory(id=-1)
        mine = [self._hands(scribe, [1, 0], [0, 1], a, b), self._hands(scribe, [1, 0.1], [0.1, 1], a, b)]
        for _ in range(3):
            self._hands(placeholder, [0, 1], [1, 0], a, b)

        score = hand_similarity.score_attributions(hand_similarity.compare(), at=1)

        assert (score.scribes, score.hands, score.found, score.possible) == (1, 2, 2, 2)
        assert score.best_ranks == [1, 1]
        assert score.percentile == pytest.approx(1.0)
        assert score.by_chance == pytest.approx(2 * 1 / 4)
        assert Scribe.objects.get(pk=-1).hand_set.count() == 3
        assert all(hand.scribe_id == scribe.pk for hand in mine)

    def test_the_placeholder_scribe_is_not_ground_truth(self):
        a, b = AllographFactory.create_batch(2)
        placeholder = ScribeFactory(id=-1)
        for _ in range(3):
            self._hands(placeholder, [1, 0], [0, 1], a, b)

        assert hand_similarity.score_attributions(hand_similarity.compare()) is None

    def test_the_harness_reports_each_encoder(self):
        a, b = AllographFactory.create_batch(2)
        scribe = ScribeFactory()
        self._hands(scribe, [1, 0], [0, 1], a, b)
        self._hands(scribe, [1, 0.1], [0.1, 1], a, b)
        self._hands(ScribeFactory(), [0, 1], [1, 0], a, b)
        out = StringIO()

        call_command("eval_hand_similarity", "--encoder", "hog", stdout=out)

        text = out.getvalue()
        assert "hog@test-1: 3 hands compared, 0 with too few glyphs" in text
        assert "1 attributed scribe(s) with two or more compared hands: 2" in text
        assert "2 of 2 (chance 2.0)" in text

    def test_the_harness_refuses_an_encoder_with_no_vectors_or_mixed_weights(self):
        hand, allograph = HandFactory(), AllographFactory()
        _glyph(hand, allograph, [1, 0])
        _glyph(hand, allograph, [1, 0], part=Part("hog", "other-weights", 2))

        with pytest.raises(CommandError, match="no stored vectors"):
            call_command("eval_hand_similarity", "--encoder", "ink")
        with pytest.raises(CommandError, match="2 different weights"):
            call_command("eval_hand_similarity", "--encoder", "hog")


class TestNearestToScribe:
    @staticmethod
    def _near(hand, other, rank: int, similarity: float) -> None:
        HandSimilarity.objects.create(
            hand=hand, other=other, rank=rank, similarity=similarity, letters=[], vectors="hog@test-1"
        )

    def test_gathers_the_hands_near_the_scribe_s_hands_those_near_most_first_then_the_more_alike(self):
        scribe = ScribeFactory()
        a, b, uncompared = HandFactory.create_batch(3, scribe=scribe)
        x, y, z, elsewhere = HandFactory.create_batch(4)
        self._near(a, b, 1, 0.9)
        self._near(a, y, 2, 0.4)
        self._near(a, x, 3, 0.3)
        self._near(b, a, 1, 0.9)
        self._near(b, x, 2, 0.2)
        self._near(b, z, 5, 0.6)
        # Only the scribe's hands' own lists count: a hand that finds the scribe is not found by it.
        self._near(elsewhere, a, 1, 0.99)

        nearest = hand_similarity.nearest_to_scribe(scribe.pk)

        assert [hand.pk for hand in nearest.hands] == [a.pk, b.pk, uncompared.pk]
        assert set(nearest.rows) == {a.pk, b.pk}
        assert [match.other.pk for match in nearest.matches] == [x.pk, z.pk, y.pk]
        x_match = nearest.matches[0]
        assert [(row.hand_id, row.rank) for row in x_match.near] == [(b.pk, 2), (a.pk, 3)]
        assert x_match.best == pytest.approx(0.3)

    def test_keeps_the_first_matches(self):
        scribe = ScribeFactory()
        hand = HandFactory(scribe=scribe)
        others = HandFactory.create_batch(3)
        for rank, other in enumerate(others, start=1):
            self._near(hand, other, rank, 1 - rank / 10)

        nearest = hand_similarity.nearest_to_scribe(scribe.pk, limit=2)

        assert [match.other.pk for match in nearest.matches] == [others[0].pk, others[1].pk]

    def test_equally_near_and_alike_matches_come_in_hand_order(self):
        scribe = ScribeFactory()
        hand = HandFactory(scribe=scribe)
        later, earlier = sorted(HandFactory.create_batch(2), key=lambda other: -other.pk)
        self._near(hand, later, 1, 0.5)
        self._near(hand, earlier, 2, 0.5)

        nearest = hand_similarity.nearest_to_scribe(scribe.pk)

        assert [match.other.pk for match in nearest.matches] == [earlier.pk, later.pk]

    def test_the_placeholder_and_an_unknown_scribe_are_no_scribe(self):
        placeholder = ScribeFactory(id=-1)
        HandFactory(scribe=placeholder)

        with pytest.raises(Scribe.DoesNotExist):
            hand_similarity.nearest_to_scribe(placeholder.pk)
        with pytest.raises(Scribe.DoesNotExist):
            hand_similarity.nearest_to_scribe(999999)

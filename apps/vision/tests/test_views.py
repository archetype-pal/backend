"""GET /api/v1/hands/{id}/similar/ (W1.3): a hand's stored nearest hands."""

from django.urls import reverse
import pytest
from rest_framework.test import APIClient

from apps.annotations.tests.factories import GraphFactory
from apps.scribes.tests.factories import HandFactory, ScribeFactory
from apps.symbols_structure.tests.factories import AllographFactory
from apps.vision.models import GlyphEmbedding, HandSimilarity
from apps.vision.services import hand_similarity

pytestmark = pytest.mark.django_db


def _url(hand_id: int) -> str:
    return str(reverse("hand-similar", kwargs={"pk": hand_id}))


def _near(hand, other, rank: int, similarity: float, letters: list[dict]) -> None:
    HandSimilarity.objects.create(
        hand=hand, other=other, rank=rank, similarity=similarity, letters=letters, vectors="hog@48px-6cell-9bin-1"
    )


def _embedded(hand, *, current: bool = True) -> None:
    part = hand_similarity.PART
    graph = GraphFactory(hand=hand)
    GlyphEmbedding.objects.create(
        graph=graph,
        encoder=part.encoder,
        model_name=part.encoder,
        model_version=part.model_version,
        dimensions=part.dimensions,
        vector=GlyphEmbedding.pack([1.0] * part.dimensions),
        crop_digest=GlyphEmbedding.crop_digest_for(graph) if current else "",
    )


class TestSimilarHands:
    def test_lists_the_nearest_hands_with_the_letters_they_are_compared_on(self):
        hand, first, second = HandFactory.create_batch(3)
        a, r = AllographFactory(name="a"), AllographFactory(name="r")
        _near(hand, second, 2, 0.21, [])
        _near(hand, first, 1, 0.35, [{"allograph": a.pk, "similarity": 0.39, "glyphs": [4, 2]}])
        _near(first, hand, 1, 0.35, [])
        HandSimilarity.objects.filter(hand=hand, rank=1).update(
            letters=[
                {"allograph": a.pk, "similarity": 0.39, "glyphs": [4, 2]},
                {"allograph": r.pk, "similarity": 0.12, "glyphs": [1, 1]},
            ]
        )
        for _ in range(3):
            _embedded(hand)

        response = APIClient().get(_url(hand.pk))

        assert response.status_code == 200
        body = response.json()
        assert (body["hand"], body["glyphs"], body["minimum_glyphs"]) == (hand.pk, 3, hand_similarity.MIN_GLYPHS)
        assert body["vectors"] == "hog@48px-6cell-9bin-1"
        assert body["computed"]
        assert [(row["rank"], row["hand"]["id"], row["similarity"]) for row in body["results"]] == [
            (1, first.pk, 0.35),
            (2, second.pk, 0.21),
        ]
        summary = body["results"][0]["hand"]
        assert summary["item_part"] == first.item_part_id
        assert summary["item_part_display_label"] == first.item_part.display_label()
        assert summary["scribe"] == {"id": first.scribe_id, "name": first.scribe.name}
        assert body["results"][0]["letters"] == [
            {"allograph": a.pk, "name": "a", "character": a.character.name, "similarity": 0.39, "glyphs": [4, 2]},
            {"allograph": r.pk, "name": "r", "character": r.character.name, "similarity": 0.12, "glyphs": [1, 1]},
        ]

    def test_the_placeholder_scribe_is_no_scribe(self):
        hand = HandFactory()
        unattributed = HandFactory(scribe=ScribeFactory(id=-1))
        _near(hand, unattributed, 1, 0.3, [])

        body = APIClient().get(_url(hand.pk)).json()

        assert body["results"][0]["hand"]["scribe"] is None

    def test_a_hand_with_no_stored_nearest_says_how_many_current_glyphs_it_has(self):
        hand = HandFactory()
        _embedded(hand)
        _embedded(hand, current=False)

        body = APIClient().get(_url(hand.pk)).json()

        assert body == {
            "hand": hand.pk,
            "glyphs": 1,
            "minimum_glyphs": hand_similarity.MIN_GLYPHS,
            "vectors": None,
            "computed": None,
            "results": [],
        }

    def test_an_unknown_hand_is_404(self):
        assert APIClient().get(_url(999999)).status_code == 404

    def test_reads_the_same_number_of_queries_however_many_results(self, django_assert_max_num_queries):
        hand = HandFactory()
        allograph = AllographFactory()
        # With no current item, a part's label is its catalogue numbers, read per part unless prefetched.
        for rank, other in enumerate(HandFactory.create_batch(8, item_part__current_item=None), start=1):
            _near(hand, other, rank, 1 / rank, [{"allograph": allograph.pk, "similarity": 0.5, "glyphs": [1, 1]}])

        with django_assert_max_num_queries(8):
            response = APIClient().get(_url(hand.pk))

        assert len(response.json()["results"]) == 8


def _scribe_url(scribe_id: int) -> str:
    # Written out, since `reverse` will not build the placeholder's negative pk.
    return f"/api/v1/scribes/{scribe_id}/similar/"


class TestScribeSimilarHands:
    def test_lists_the_hands_near_the_scribe_s_and_where_its_own_hands_find_each_other(self):
        scribe = ScribeFactory()
        assert _scribe_url(scribe.pk) == reverse("scribe-similar", kwargs={"pk": scribe.pk})
        a, b, uncompared = HandFactory.create_batch(3, scribe=scribe)
        x, w = HandFactory.create_batch(2)
        _near(a, b, 1, 0.6, [])
        _near(a, w, 2, 0.55, [])
        _near(a, x, 3, 0.5, [])
        _near(b, a, 1, 0.6, [])
        _near(b, x, 2, 0.3, [])

        response = APIClient().get(_scribe_url(scribe.pk))

        assert response.status_code == 200
        body = response.json()
        assert (body["scribe"], body["minimum_glyphs"], body["vectors"]) == (
            scribe.pk,
            hand_similarity.MIN_GLYPHS,
            "hog@48px-6cell-9bin-1",
        )
        assert body["computed"]
        assert body["hands"] == [
            {
                "id": a.pk,
                "name": a.name,
                "item_part": a.item_part_id,
                "item_part_display_label": a.item_part.display_label(),
                "compared": True,
                "siblings": [{"hand": b.pk, "rank": 1, "similarity": 0.6}],
            },
            {
                "id": b.pk,
                "name": b.name,
                "item_part": b.item_part_id,
                "item_part_display_label": b.item_part.display_label(),
                "compared": True,
                "siblings": [{"hand": a.pk, "rank": 1, "similarity": 0.6}],
            },
            {
                "id": uncompared.pk,
                "name": uncompared.name,
                "item_part": uncompared.item_part_id,
                "item_part_display_label": uncompared.item_part.display_label(),
                "compared": False,
                "siblings": [],
            },
        ]
        assert [match["hand"]["id"] for match in body["results"]] == [x.pk, w.pk]
        match = body["results"][0]
        assert match["hand"]["scribe"] == {"id": x.scribe_id, "name": x.scribe.name}
        # The best likeness, which is not the nearest rank's: ranks are counted in each hand's own list.
        assert match["similarity"] == 0.5
        assert match["near"] == [
            {"hand": b.pk, "rank": 2, "similarity": 0.3},
            {"hand": a.pk, "rank": 3, "similarity": 0.5},
        ]

    def test_a_scribe_with_nothing_compared_lists_its_hands_and_no_matches(self):
        scribe = ScribeFactory()
        hand = HandFactory(scribe=scribe)

        body = APIClient().get(_scribe_url(scribe.pk)).json()

        assert (body["vectors"], body["computed"], body["results"]) == (None, None, [])
        assert [(row["id"], row["compared"]) for row in body["hands"]] == [(hand.pk, False)]

    def test_the_placeholder_and_an_unknown_scribe_are_404(self):
        placeholder = ScribeFactory(id=-1)

        assert APIClient().get(_scribe_url(placeholder.pk)).status_code == 404
        assert APIClient().get(_scribe_url(999999)).status_code == 404

    def test_reads_the_same_number_of_queries_however_many_hands_and_matches(self, django_assert_max_num_queries):
        scribe = ScribeFactory()
        mine = HandFactory.create_batch(4, scribe=scribe, item_part__current_item=None)
        others = HandFactory.create_batch(6, item_part__current_item=None)
        for hand in mine:
            for rank, other in enumerate(others, start=1):
                _near(hand, other, rank, 1 / rank, [])

        with django_assert_max_num_queries(5):
            response = APIClient().get(_scribe_url(scribe.pk))

        assert len(response.json()["results"]) == 6

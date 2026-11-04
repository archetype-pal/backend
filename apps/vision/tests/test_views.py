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

"""Conversational annotation (W3.4): reading "label every long-s on this folio" and proposing the rest.

The page is drawn at full size, and the image server is replaced by one that
renders it at whatever width is asked: hooked stems ("s, long"), rings ("o")
and one round s, in cell-aligned squares of parchment.
"""

import io
import json
from unittest import mock

from django.core.management import call_command
import numpy as np
from PIL import Image, ImageDraw
import pytest

from apps.annotations.models import Graph, GraphProposal
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.services.iiif import get_iiif_region_from_geojson
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.models import MLJob
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory, CharacterFactory
from apps.vision import images
from apps.vision.services import page_search

pytestmark = pytest.mark.django_db

WIDTH, HEIGHT = 1280, 880
SPACING = 192
STEMS = [(0, 0), (2, 0), (4, 1), (1, 2), (3, 3), (5, 3)]
RINGS = [(1, 0), (3, 1), (0, 2)]


def _centre(slot: tuple[int, int]) -> tuple[int, int]:
    column, row = slot
    return 120 + column * SPACING, 120 + row * SPACING


def _box(slot: tuple[int, int]) -> tuple[float, float, float, float]:
    cx, cy = _centre(slot)
    return float(cx - 24), float(cy - 36), 48.0, 72.0


def _drawn() -> Image.Image:
    image = Image.new("L", (WIDTH, HEIGHT), 225)
    draw = ImageDraw.Draw(image)
    for cx, cy in map(_centre, STEMS):
        draw.line([(cx - 4, cy - 24), (cx - 4, cy + 32)], fill=35, width=10)
        draw.arc([(cx - 4, cy - 36), (cx + 24, cy - 12)], start=180, end=360, fill=35, width=8)
    for cx, cy in map(_centre, RINGS):
        draw.ellipse([(cx - 20, cy - 20), (cx + 20, cy + 20)], outline=35, width=8)
    return image


def _ring(box: tuple[float, float, float, float]) -> dict:
    x, y, w, h = box
    return images.ring_from_box(
        {"x": x / WIDTH, "y": y / HEIGHT, "w": w / WIDTH, "h": h / HEIGHT}, width=WIDTH, height=HEIGHT
    )


def _rendition(image, *, width: int) -> bytes:
    buffer = io.BytesIO()
    _drawn().resize((width, round(HEIGHT * width / WIDTH)), Image.Resampling.BILINEAR).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def server():
    """The image server: the page's size, and the page at any width."""
    with (
        mock.patch("apps.vision.images.dimensions", return_value=(WIDTH, HEIGHT)),
        mock.patch("apps.vision.images.rendition", side_effect=_rendition) as rendition,
    ):
        yield rendition


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = False
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


@pytest.fixture
def folio():
    """A page with three long s and two rings marked by one hand, and a round s."""
    image = ItemImageFactory()
    hand = HandFactory()
    s = CharacterFactory(name="s")
    # Made first, so a lower key than the long s it has fewer examples than.
    round_s = AllographFactory(character=s, name="round")
    long_s = AllographFactory(character=s, name="long")
    o = AllographFactory(character=CharacterFactory(name="o"), name="o")
    for slot in STEMS[:3]:
        GraphFactory(item_image=image, hand=hand, allograph=long_s, annotation=_ring(_box(slot)))
    for slot in RINGS[:2]:
        GraphFactory(item_image=image, hand=hand, allograph=o, annotation=_ring(_box(slot)))
    GraphFactory(item_image=image, hand=hand, allograph=round_s, annotation=_ring(_box(RINGS[2])))
    return {"image": image, "hand": hand, "long_s": long_s, "round_s": round_s, "o": o}


def _region(annotation: dict) -> tuple[float, ...]:
    return tuple(float(v) for v in get_iiif_region_from_geojson(json.dumps(annotation), image_height=HEIGHT).split(","))


def _centre_of(annotation: dict) -> tuple[float, float]:
    x, y, w, h = _region(annotation)
    return x + w / 2, y + h / 2


def _slot_of(annotation: dict, slots: list[tuple[int, int]]) -> tuple[int, int] | None:
    cx, cy = _centre_of(annotation)
    for slot in slots:
        x, y, w, h = _box(slot)
        if x <= cx <= x + w and y <= cy <= y + h:
            return slot
    return None


class TestPageLetters:
    def test_groups_the_page_s_glyphs_by_letter_and_marks_everything_on_it(self, server, folio):
        image, hand = folio["image"], folio["hand"]
        GraphFactory(
            item_image=image,
            hand=hand,
            allograph=folio["o"],
            annotation=_ring(_box(RINGS[2])),
            deleted_at="2026-11-01T00:00:00Z",
        )
        GraphFactory(
            item_image=image,
            hand=hand,
            allograph=folio["o"],
            annotation_type=Graph.AnnotationType.TEXT,
            annotation=_ring((700.0, 700.0, 40.0, 60.0)),
        )
        GraphFactory(item_image=image, hand=hand, allograph=folio["o"], annotation={"no": "geometry"})
        GraphFactory(allograph=folio["o"], annotation=_ring((800.0, 100.0, 40.0, 60.0)))  # another page
        pending = GraphProposal.objects.create(item_image=image, annotation=_ring((900.0, 500.0, 40.0, 60.0)))
        GraphProposal.objects.create(
            item_image=image, annotation=_ring((1000.0, 500.0, 40.0, 60.0)), status=GraphProposal.Status.REJECTED
        )

        letters = page_search.page_letters(image)

        assert (letters.width, letters.height) == (WIDTH, HEIGHT)
        assert {allograph: len(rows) for allograph, rows in letters.by_allograph.items()} == {
            folio["long_s"].pk: 3,
            folio["o"].pk: 2,
            folio["round_s"].pk: 1,
        }
        [(graph, box)] = letters.by_allograph[folio["round_s"].pk]
        assert box == pytest.approx(_box(RINGS[2]), abs=1)
        marked = sorted(
            [_box(slot) for slot in STEMS[:3] + RINGS] + [(900.0, 500.0, 40.0, 60.0), (1000.0, 500.0, 40.0, 60.0)]
        )
        assert sorted(letters.marked) == [pytest.approx(box, abs=1) for box in marked]
        assert pending.status == GraphProposal.Status.PENDING

    def test_an_unmeasurable_page_is_unavailable(self, folio):
        with (
            mock.patch("apps.vision.images.dimensions", side_effect=images.ImageUnavailable("gone")),
            pytest.raises(images.ImageUnavailable),
        ):
            page_search.page_letters(folio["image"])

    def test_a_letter_s_examples_are_the_typical_ones_by_the_hand_asked_for(self, server, folio):
        image, long_s = folio["image"], folio["long_s"]
        other_hand = HandFactory()
        GraphFactory(item_image=image, hand=other_hand, allograph=long_s, annotation=_ring(_box(STEMS[3])))
        GraphFactory(
            item_image=image, hand=folio["hand"], allograph=long_s, annotation=_ring((10.0, 10.0, 600.0, 200.0))
        )

        letters = page_search.page_letters(image)

        assert len(letters.examples(long_s.pk)) == 4
        assert len(letters.examples(long_s.pk, folio["hand"].pk)) == 3
        assert [graph.hand_id for graph, _ in letters.examples(long_s.pk, other_hand.pk)] == [other_hand.pk]


def test_typical_keeps_boxes_within_half_to_twice_the_median_side():
    boxes = [(0, 0, 10, 20), (0, 0, 20, 10), (0, 0, 9, 9), (0, 0, 10, 40), (0, 0, 41, 10), (0, 0, 20, 20)]

    assert page_search.typical(boxes) == [(0, 0, 10, 20), (0, 0, 20, 10), (0, 0, 10, 40), (0, 0, 20, 20)]
    assert page_search.typical([]) == []


class TestReadRequest:
    @pytest.fixture
    def letters(self, server, folio):
        return page_search.page_letters(folio["image"])

    @pytest.mark.parametrize(
        ("request_text", "expected"),
        [
            ("label every long-s on this folio", ["long_s"]),
            ("Label every LONG s", ["long_s"]),
            ("the round s, please", ["round_s"]),
            ("every o", ["o"]),
            # Its character alone: every letter of it, the most examples first.
            ("every s", ["long_s", "round_s"]),
            # S is not s.
            ("every S", []),
            ("every q", []),
            ("long", []),
        ],
    )
    def test_names_the_letters_on_the_page_it_can_mean(self, letters, folio, request_text, expected):
        assert page_search.read_request(request_text, letters) == [folio[name] for name in expected]

    def test_a_letter_is_named_only_by_every_word_of_its_allograph_s_name(self, server, folio):
        hooked = AllographFactory(character=folio["long_s"].character, name="long hooked")
        GraphFactory(
            item_image=folio["image"],
            hand=folio["hand"],
            allograph=hooked,
            annotation=_ring((600.0, 600.0, 40.0, 60.0)),
        )
        letters = page_search.page_letters(folio["image"])

        assert page_search.read_request("every long s", letters) == [folio["long_s"]]
        assert page_search.read_request("every hooked long s", letters) == [folio["long_s"], hooked]

    def test_a_character_named_by_a_word_is_matched_whatever_its_case(self, server, folio):
        et = AllographFactory(character=CharacterFactory(name="et"), name="tironian")
        GraphFactory(
            item_image=folio["image"], hand=folio["hand"], allograph=et, annotation=_ring((600.0, 600.0, 40.0, 60.0))
        )
        letters = page_search.page_letters(folio["image"])

        assert page_search.read_request("Every Tironian ET", letters) == [et]


class TestFindOnPage:
    def test_files_the_letter_s_other_places_as_proposals_of_one_ledger_job(self, server, enabled, folio):
        letters = page_search.page_letters(folio["image"])

        search = page_search.find_on_page(letters, folio["long_s"], count=3)

        assert (search.allograph, search.hand, search.examples) == (folio["long_s"], folio["hand"], 3)
        assert (search.job.task, search.job.provider, search.job.status) == ("W3.4", "hog-page", MLJob.Status.SUCCEEDED)
        assert search.job.params["item_image"] == folio["image"].pk
        assert sorted(search.job.params["examples"]) == sorted(
            graph.pk for graph, _ in letters.examples(folio["long_s"].pk)
        )
        # The examples' side, 72 pixels, is rendered as one 48-pixel window.
        server.assert_called_once_with(folio["image"], width=round(WIDTH * 48 / 72))
        proposals = GraphProposal.objects.filter(ml_job=search.job).order_by("-confidence")
        assert list(proposals) == sorted(search.proposals, key=lambda proposal: -proposal.confidence)
        assert {_slot_of(proposal.annotation, STEMS) for proposal in proposals} == set(STEMS[3:])
        for proposal in proposals:
            assert (proposal.allograph, proposal.hand, proposal.status) == (
                folio["long_s"],
                folio["hand"],
                GraphProposal.Status.PENDING,
            )
            assert proposal.annotation_type == Graph.AnnotationType.IMAGE
            assert proposal.confidence > 0.5
            _, _, w, h = _region(proposal.annotation)
            assert (w, h) == pytest.approx((48, 72), abs=2)

    def test_measures_the_page_it_was_given_not_the_one_it_asked_for(self, server, enabled, folio):
        # An image server that rounds, or ignores the width, sends back another size; the boxes must follow it.
        server.side_effect = lambda image, *, width: _rendition(image, width=round(width * 1.5))
        letters = page_search.page_letters(folio["image"])

        search = page_search.find_on_page(letters, folio["long_s"], count=3)

        assert {_slot_of(proposal.annotation, STEMS) for proposal in search.proposals} == set(STEMS[3:])

    def test_asking_again_finds_the_next_places(self, server, enabled, folio):
        first = page_search.find_on_page(page_search.page_letters(folio["image"]), folio["long_s"], count=2)
        second = page_search.find_on_page(page_search.page_letters(folio["image"]), folio["long_s"], count=1)

        found = [_slot_of(proposal.annotation, STEMS) for proposal in first.proposals + second.proposals]
        assert sorted(found) == sorted(STEMS[3:])

    def test_searches_by_one_hand_s_examples_when_asked(self, server, enabled, folio):
        other = HandFactory()
        GraphFactory(item_image=folio["image"], hand=other, allograph=folio["long_s"], annotation=_ring(_box(STEMS[3])))
        GraphFactory(item_image=folio["image"], hand=other, allograph=folio["long_s"], annotation=_ring(_box(STEMS[4])))
        letters = page_search.page_letters(folio["image"])

        mixed = page_search.find_on_page(letters, folio["long_s"], count=1)
        theirs = page_search.find_on_page(letters, folio["long_s"], hand=other, count=1)

        assert (mixed.hand, mixed.examples) == (None, 5)
        assert mixed.proposals[0].hand is None
        assert (theirs.hand, theirs.examples) == (other, 2)
        assert theirs.proposals[0].hand == other

    def test_too_few_examples_is_said_rather_than_searched(self, server, enabled, folio):
        letters = page_search.page_letters(folio["image"])

        with pytest.raises(page_search.CannotSearch) as refused:
            page_search.find_on_page(letters, folio["round_s"])

        assert refused.value.reason == "too_few_examples"
        assert refused.value.details == {"examples": 1, "minimum": page_search.MIN_EXAMPLES}
        server.assert_not_called()

    def test_letters_too_small_for_the_page_are_refused(self, server, enabled, folio, monkeypatch):
        monkeypatch.setattr(page_search, "MAX_RENDITION", 800)
        letters = page_search.page_letters(folio["image"])

        with pytest.raises(page_search.CannotSearch) as refused:
            page_search.find_on_page(letters, folio["long_s"])

        assert (refused.value.reason, refused.value.details) == ("page_too_large", {"side": 72, "maximum": 800})
        server.assert_not_called()

    def test_a_refused_search_files_nothing_and_the_ledger_says_why(self, server, folio, settings):
        settings.ML_INFERENCE_ENABLED = False
        letters = page_search.page_letters(folio["image"])

        search = page_search.find_on_page(letters, folio["long_s"])

        assert search.job.status == MLJob.Status.REFUSED
        assert search.proposals == []
        assert not GraphProposal.objects.exists()


@pytest.fixture
def marked_folio(folio):
    """The folio with all six long s marked, so three can be shown and three hidden."""
    for slot in STEMS[3:]:
        GraphFactory(
            item_image=folio["image"], hand=folio["hand"], allograph=folio["long_s"], annotation=_ring(_box(slot))
        )
    return folio


def _mark_every_long_s(image, hand, long_s) -> None:
    for slot in STEMS:
        GraphFactory(item_image=image, hand=hand, allograph=long_s, annotation=_ring(_box(slot)))


class TestEvaluate:
    def test_hides_all_but_the_examples_shown_and_counts_the_ones_found_again(self, server, marked_folio):
        result = page_search.evaluate(shown=3)

        # Only the long s has the six examples that showing three and hiding three needs.
        assert (result.letters, result.pages, result.shown, result.hidden) == (1, 1, 3, 3)
        assert (result.within_hidden, result.within_thrice, result.unavailable_pages) == (3, 3, 0)
        # Rendered at two thirds, so the 72-pixel letters span 48: 90 × 135 windows, 150 places a window apart.
        server.assert_called_once_with(marked_folio["image"], width=853)
        assert result.by_chance == pytest.approx(3 * 3 / 150)
        assert result.by_chance_thrice == pytest.approx(3 * 9 / 150)

    def test_counts_a_hidden_example_by_the_rank_of_the_proposal_that_finds_it(self, server, marked_folio):
        scale = 853 / WIDTH  # the rendition's width over the page's
        seen: dict[str, set] = {}

        def search(grey, examples, marked, count):
            seen["shown"] = {tuple(round(v / scale) for v in box) for box in examples}
            seen["marked"] = {tuple(round(v / scale) for v in box) for box in marked}
            seen["count"] = count
            hidden = [_box(slot) for slot in STEMS if _box(slot) not in seen["shown"]]
            # A miss, two hidden examples, the first again, the shown ones, and the last hidden example eighth.
            miss = (900.0, 700.0, 48.0, 72.0)
            boxes = [miss, hidden[0], hidden[1], hidden[0], *sorted(seen["shown"]), hidden[2]]
            return [
                {"x": x * scale, "y": y * scale, "w": w * scale, "h": h * scale, "score": 0.5} for x, y, w, h in boxes
            ]

        with mock.patch("apps.ml.providers.page_search.find", side_effect=search):
            result = page_search.evaluate(shown=3)

        assert (result.within_hidden, result.within_thrice) == (2, 3)
        hidden = {_box(slot) for slot in STEMS} - seen["shown"]
        assert (len(seen["shown"]), len(hidden), seen["count"]) == (3, 3, 9)
        # What is shown stays marked; what is hidden is unmarked, as if no one had marked it yet.
        assert seen["shown"] <= seen["marked"] and not hidden & seen["marked"]

    def test_measures_the_page_it_was_given_not_the_one_it_asked_for(self, server, marked_folio):
        server.side_effect = lambda image, *, width: _rendition(image, width=round(width * 1.5))

        result = page_search.evaluate(shown=3)

        assert (result.hidden, result.within_hidden) == (3, 3)

    def test_stops_at_the_letters_asked_for_and_the_letters_per_page(self, server, marked_folio):
        other_page = ItemImageFactory()
        _mark_every_long_s(other_page, marked_folio["hand"], marked_folio["long_s"])
        _mark_every_long_s(marked_folio["image"], HandFactory(), marked_folio["long_s"])

        assert (page_search.evaluate().letters, page_search.evaluate().pages) == (3, 2)
        assert (page_search.evaluate(letters=1).letters, page_search.evaluate(letters=1).pages) == (1, 1)
        assert page_search.evaluate(per_page=1).letters == 2

    def test_fetches_no_page_past_the_letters_asked_for(self, server, marked_folio):
        _mark_every_long_s(ItemImageFactory(), marked_folio["hand"], marked_folio["long_s"])

        with mock.patch("apps.vision.images.dimensions", return_value=(WIDTH, HEIGHT)) as dimensions:
            page_search.evaluate(letters=1)

        assert dimensions.call_count == 1

    def test_a_letter_needs_three_more_examples_than_are_shown(self, server, marked_folio):
        # The long s has six: enough to show three, not four.
        assert page_search.evaluate(shown=3).letters == 1
        assert page_search.evaluate(shown=4).letters == 0

    def test_the_seed_draws_the_pages(self, server, marked_folio):
        pages = [marked_folio["image"]] + [ItemImageFactory() for _ in range(3)]
        for page in pages[1:]:
            _mark_every_long_s(page, marked_folio["hand"], marked_folio["long_s"])

        def first(seed: int):
            server.reset_mock()
            page_search.evaluate(letters=1, seed=seed)
            return server.call_args.args[0]

        assert first(7) == first(7)
        assert len({first(seed).pk for seed in range(8)}) > 1

    def test_chance_finds_every_hidden_example_on_a_page_with_fewer_places_than_them(self, server, marked_folio):
        # One window and a little more: a single place, and three hidden examples.
        with (
            mock.patch("apps.ml.providers.page_search.page_grey", return_value=np.zeros((60, 60))),
            mock.patch("apps.ml.providers.page_search.find", return_value=[]),
        ):
            result = page_search.evaluate(shown=3)

        assert (result.hidden, result.by_chance, result.by_chance_thrice) == (3, 3.0, 3.0)

    def test_the_same_seed_hides_the_same_examples(self, server, marked_folio):
        def shown(seed: int) -> list:
            with mock.patch("apps.ml.providers.page_search.find", return_value=[]) as find:
                page_search.evaluate(seed=seed)
            return list(find.call_args.args[1])

        assert shown(7) == shown(7)
        assert any(shown(seed) != shown(7) for seed in range(8, 12))

    def test_a_page_the_image_server_cannot_give_is_counted_and_passed_over(self, server, marked_folio):
        server.side_effect = images.ImageUnavailable("No image.")

        result = page_search.evaluate()

        assert (result.unavailable_pages, result.letters, result.pages, result.hidden) == (1, 0, 0, 0)

    def test_a_page_the_image_server_cannot_measure_is_counted_and_passed_over(self, marked_folio):
        with mock.patch("apps.vision.images.dimensions", side_effect=images.ImageUnavailable("No image.")):
            result = page_search.evaluate()

        assert (result.unavailable_pages, result.letters, result.pages) == (1, 0, 0)

    def test_letters_too_small_for_their_page_are_passed_over(self, server, marked_folio, monkeypatch):
        monkeypatch.setattr(page_search, "MAX_RENDITION", 800)

        result = page_search.evaluate()

        assert (result.letters, result.unavailable_pages) == (0, 0)
        server.assert_not_called()

    def test_a_letter_the_search_cannot_start_from_is_passed_over(self, server, marked_folio):
        from apps.ml.providers.base import ProviderError

        with mock.patch("apps.ml.providers.page_search.find", side_effect=ProviderError("No example lies wholly.")):
            result = page_search.evaluate()

        assert (result.letters, result.pages, result.hidden) == (0, 0, 0)


class TestEvalPageSearchCommand:
    @staticmethod
    def _run(monkeypatch, result: page_search.Evaluation, *args: str) -> tuple[mock.Mock, list[str]]:
        evaluate = mock.Mock(return_value=result)
        monkeypatch.setattr(page_search, "evaluate", evaluate)
        out = io.StringIO()
        call_command("eval_page_search", *args, stdout=out)
        return evaluate, out.getvalue().splitlines()

    def test_reports_the_share_found_against_chance(self, monkeypatch):
        result = page_search.Evaluation(
            letters=40,
            pages=26,
            shown=3,
            hidden=169,
            within_hidden=37,
            within_thrice=69,
            unavailable_pages=143,
            by_chance=1.1,
            by_chance_thrice=3.2,
        )

        evaluate, lines = self._run(monkeypatch, result, "--shown", "5", "--letters", "80", "--seed", "3")

        evaluate.assert_called_once_with(shown=5, letters=80, seed=3)
        assert lines == [
            "hog-page@48px-6cell-9bin-centred-1: 40 letters on 26 pages, 3 examples shown each; "
            "143 pages could not be fetched",
            "  of 169 hidden examples, 37 (22%) were among as many proposals as were hidden, "
            "69 (41%) among three times as many (by chance 1.1 and 3.2)",
            "  a lower bound: the pages are annotated in part, and a proposal on an unmarked example counts as a miss",
        ]

    def test_says_when_there_was_nothing_to_score(self, monkeypatch):
        result = page_search.Evaluation(
            letters=0, pages=0, shown=3, hidden=0, within_hidden=0, within_thrice=0, unavailable_pages=2
        )

        evaluate, lines = self._run(monkeypatch, result)

        evaluate.assert_called_once_with(shown=3, letters=40, seed=7)
        assert lines[1:] == ["  no letter had enough examples to hide any; nothing to score"]

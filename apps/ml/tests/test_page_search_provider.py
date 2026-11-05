"""The page search behind W3.4: a letter's other examples on a page, from the ones marked there.

The page is drawn: hooked stems, like a long s, and rings, like an o, each in a
cell-aligned square of parchment, so every answer is known.
"""

import base64
import io

import numpy as np
from PIL import Image, ImageDraw
import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, content_digest, page_search, resolve_provider
from apps.ml.providers.page_search import PageSearchProvider, find, page_blocks, scores, window
from apps.ml.providers.shape import HOG_CELL, HOG_SIDE, hog
from apps.ml.services import InferenceService

GROUND, INK = 225, 35
SPACING = 96  # a multiple of the cell, so each glyph sits the same way on the grid
STEMS = [(0, 0), (2, 0), (4, 1), (1, 2), (3, 3), (5, 3)]
RINGS = [(1, 0), (3, 1), (0, 2), (5, 1), (2, 3), (4, 3)]


def _centre(slot: tuple[int, int]) -> tuple[int, int]:
    column, row = slot
    return 60 + column * SPACING, 60 + row * SPACING


def _box(slot: tuple[int, int]) -> list[float]:
    """The glyph's box, [x, y, w, h], as an annotator would draw it."""
    cx, cy = _centre(slot)
    return [cx - 12.0, cy - 18.0, 24.0, 36.0]


def _page(stems=STEMS, rings=RINGS) -> Image.Image:
    image = Image.new("L", (640, 440), GROUND)
    draw = ImageDraw.Draw(image)
    for cx, cy in map(_centre, stems):
        draw.line([(cx - 2, cy - 12), (cx - 2, cy + 16)], fill=INK, width=5)
        draw.arc([(cx - 2, cy - 18), (cx + 12, cy - 6)], start=180, end=360, fill=INK, width=4)
    for cx, cy in map(_centre, rings):
        draw.ellipse([(cx - 10, cy - 10), (cx + 10, cy + 10)], outline=INK, width=4)
    return image


def _grey(image: Image.Image) -> np.ndarray:
    return np.asarray(image, dtype=np.float64)


def _png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _slot_of(proposal: dict, slots: list[tuple[int, int]]) -> tuple[int, int] | None:
    cx, cy = proposal["x"] + proposal["w"] / 2, proposal["y"] + proposal["h"] / 2
    for slot in slots:
        x, y, w, h = _box(slot)
        if x <= cx <= x + w and y <= cy <= y + h:
            return slot
    return None


class TestPageBlocks:
    def test_a_window_is_the_hog_encoder_s_description_of_its_48_pixels_less_the_page_s_mean(self):
        grey = _grey(_page())
        blocks = page_blocks(grey)
        windows, patches = [], []
        for slot in (STEMS[0], RINGS[0]):
            cx, cy = _centre(slot)
            windows.append(window(blocks, cx, cy))
            top, left = cy - HOG_SIDE // 2, cx - HOG_SIDE // 2
            assert top % HOG_CELL == 0 and left % HOG_CELL == 0
            patches.append(hog(grey[top : top + HOG_SIDE, left : left + HOG_SIDE]).reshape(windows[-1].shape))

        # The page's mean block is the same for both, so it drops out of their difference.
        assert np.allclose(windows[0] - windows[1], patches[0] - patches[1])
        assert np.allclose(blocks.reshape(-1, blocks.shape[-1]).mean(0), 0)

    def test_a_window_that_runs_off_the_page_is_none(self):
        blocks = page_blocks(_grey(_page()))
        last_row = blocks.shape[0] - page_search.WINDOW_BLOCKS
        last_col = blocks.shape[1] - page_search.WINDOW_BLOCKS

        def centre(index: int) -> int:
            return index * HOG_CELL + HOG_SIDE // 2

        assert window(blocks, 10, 220) is None
        assert window(blocks, centre(last_col), centre(last_row)).shape == (7, 7, 36)
        assert window(blocks, centre(last_col), centre(last_row + 1)) is None
        assert window(blocks, centre(last_col + 1), centre(last_row)) is None

    def test_scores_each_window_by_its_cosine_to_the_template(self):
        blocks = page_blocks(_grey(_page()))
        stem = window(blocks, *_centre(STEMS[0]))
        ring = window(blocks, *_centre(RINGS[0]))
        grid = scores(blocks, 3 * stem)

        def at(slot):
            cx, cy = _centre(slot)
            return grid[(cy - HOG_SIDE // 2) // HOG_CELL, (cx - HOG_SIDE // 2) // HOG_CELL]

        assert at(STEMS[0]) == pytest.approx(1.0)
        assert at(RINGS[0]) == pytest.approx(float((stem * ring).sum() / np.linalg.norm(stem) / np.linalg.norm(ring)))
        assert grid.max() == pytest.approx(1.0) and grid.min() >= -1.0

    def test_a_page_smaller_than_a_window_is_refused(self):
        with pytest.raises(ProviderError, match="smaller than one window"):
            page_blocks(np.full((40, 400), GROUND, dtype=np.float64))


class TestFind:
    def test_proposes_the_letter_s_other_examples_best_first_and_not_the_other_letter(self):
        examples = [_box(STEMS[0]), _box(STEMS[1])]

        proposals = find(_grey(_page()), examples, [], count=4)

        assert {_slot_of(proposal, STEMS) for proposal in proposals} == set(STEMS[2:])
        scores = [proposal["score"] for proposal in proposals]
        assert scores == sorted(scores, reverse=True)
        assert all(proposal["score"] > 0.5 for proposal in proposals)

    def test_a_proposal_is_the_examples_median_size_centred_on_its_window(self):
        examples = [[48.0, 40.0, 20.0, 34.0], _box(STEMS[1]), [432.0, 138.0, 30.0, 40.0]]

        [proposal] = find(_grey(_page()), examples, [], count=1)

        assert (proposal["w"], proposal["h"]) == (24.0, 36.0)
        slot = _slot_of(proposal, STEMS)
        assert (proposal["x"] + 12, proposal["y"] + 18) == _centre(slot)

    def test_searches_by_the_mean_of_the_examples(self):
        grey = _grey(_page())
        examples = [_box(STEMS[0]), _box(RINGS[0])]

        [proposal] = find(grey, examples, [], count=1)

        blocks = page_blocks(grey)
        parts = [window(blocks, *_centre(slot)) for slot in (STEMS[0], RINGS[0])]
        template = np.mean([part / np.linalg.norm(part) for part in parts], axis=0)
        found = window(blocks, proposal["x"] + 12, proposal["y"] + 18)
        assert proposal["score"] == pytest.approx(
            float((found * template).sum() / np.linalg.norm(found) / np.linalg.norm(template)), abs=1e-4
        )

    def test_never_proposes_an_example_or_a_marked_box(self):
        examples = [_box(STEMS[0]), _box(STEMS[1])]
        marked = [_box(STEMS[2]), _box(STEMS[3])]

        proposals = find(_grey(_page()), examples, marked, count=40)

        found = [_slot_of(proposal, STEMS) for proposal in proposals]
        assert set(STEMS[4:]) <= set(found)
        assert not {STEMS[0], STEMS[1], STEMS[2], STEMS[3]} & set(found)

    def test_a_marked_box_drawn_a_little_off_its_letter_still_covers_it(self):
        x, y, w, h = _box(STEMS[2])
        x2, y2, w2, h2 = _box(STEMS[3])
        # Each letter's centre lies 2 pixels past its box, right of one and below the other: within the 15% margin.
        marked = [[x - w / 2 - 2, y, w, h], [x2, y2 - h2 / 2 - 2, w2, h2]]

        proposals = find(_grey(_page()), [_box(STEMS[0])], marked, count=40)

        found = {_slot_of(proposal, STEMS) for proposal in proposals}
        assert STEMS[2] not in found and STEMS[3] not in found
        assert STEMS[4] in found

    def test_keeps_proposals_more_than_half_a_letter_apart(self):
        proposals = find(_grey(_page()), [_box(STEMS[0])], [], count=40)

        centres = [(p["x"] + p["w"] / 2, p["y"] + p["h"] / 2) for p in proposals]
        apart = page_search.SUPPRESS_CELLS * HOG_CELL
        assert len(centres) > 10
        for i, (ax, ay) in enumerate(centres):
            for bx, by in centres[i + 1 :]:
                assert max(abs(ax - bx), abs(ay - by)) > apart

    def test_an_example_whose_window_runs_off_the_page_says_so(self):
        with pytest.raises(ProviderError, match="No example lies wholly on the page"):
            find(_grey(_page()), [[0.0, 0.0, 10.0, 10.0]], [], count=3)


class TestProvider:
    def test_reads_the_page_and_returns_the_boxes(self):
        page = _page()
        examples = [_box(STEMS[0]), _box(STEMS[1])]
        inputs = {"page": _png(page), "examples": examples, "marked": [_box(STEMS[2])], "count": 3}

        result = PageSearchProvider().run(InferenceRequest(task="W3.4", inputs=inputs))

        assert result.output == {"boxes": find(_grey(page), examples, [_box(STEMS[2])], 3)}
        assert (result.model_name, result.model_version) == ("hog-page", "48px-6cell-9bin-centred-1")
        assert result.cost_micros == 0
        assert result.prompt_hash == content_digest(
            {"page": inputs["page"], "examples": examples, "marked": [_box(STEMS[2])], "count": 3}
        )

    def test_marked_boxes_are_optional(self):
        inputs = {"page": _png(_page()), "examples": [_box(STEMS[0])], "count": 2}

        result = PageSearchProvider().run(InferenceRequest(task="W3.4", inputs=inputs))

        assert len(result.output["boxes"]) == 2

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"page": None}, "base64 image"),
            ({"page": "not base64!"}, "not a PNG or JPEG"),
            ({"page": "aGVsbG8="}, "not a PNG or JPEG"),
            ({"examples": []}, "no examples"),
            ({"examples": [[1, 2, 3]]}, "`examples` must be"),
            ({"examples": "x"}, "`examples` must be"),
            ({"marked": [[1, 2, "3", 4]]}, "`marked` must be"),
            ({"count": 0}, "`count` must be"),
            ({"count": page_search.MAX_COUNT + 1}, "`count` must be"),
            ({"count": True}, "`count` must be"),
            ({"count": "5"}, "`count` must be"),
        ],
    )
    def test_refuses_what_it_cannot_read(self, change, message):
        inputs = {"page": _png(_page()), "examples": [_box(STEMS[0])], "marked": [], "count": 3, **change}

        with pytest.raises(ProviderError, match=message):
            PageSearchProvider().run(InferenceRequest(task="W3.4", inputs=inputs))

    def test_refuses_a_page_larger_than_it_searches(self, monkeypatch):
        monkeypatch.setattr(page_search, "MAX_SIDE", 600)
        inputs = {"page": _png(_page()), "examples": [_box(STEMS[0])], "count": 3}

        with pytest.raises(ProviderError, match="640 × 440; the most this searches is 600"):
            PageSearchProvider().run(InferenceRequest(task="W3.4", inputs=inputs))


@pytest.mark.django_db
def test_is_self_hosted_and_runs_through_the_ledger(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = False
    inputs = {"page": _png(_page()), "examples": [_box(STEMS[0])], "count": 2}
    service = InferenceService()

    job = service.submit(task="W3.4", provider="hog-page", inputs=inputs, dispatch=False)
    job = service.run(job.pk, inputs=inputs)

    assert resolve_provider("hog-page").hosted is False
    assert (job.status, job.model_name, job.cost_micros) == (MLJob.Status.SUCCEEDED, "hog-page", 0)
    assert len(job._output["boxes"]) == 2

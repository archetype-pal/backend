"""The classical shape descriptors, `ink` and `hog`: what they see in a glyph and what they ignore."""

import base64
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageOps
import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, content_digest, resolve_provider
from apps.ml.providers.pixels import pixel_vector
from apps.ml.providers.shape import (
    HOG_DIMENSIONS,
    INK_SIDE,
    HogProvider,
    InkProvider,
    hog_vector,
    ink_vector,
    otsu_threshold,
)
from apps.ml.services import InferenceService

PARCHMENT = (232, 220, 190)
INK = (40, 30, 20)


def _bar(width=20, height=60, *, ground=PARCHMENT, ink=INK, left=8) -> Image.Image:
    image = Image.new("RGB", (width, height), ground)
    ImageDraw.Draw(image).rectangle((left, 4, left + 4, height - 4), fill=ink)
    return image


def _lit_unevenly(image: Image.Image) -> Image.Image:
    """The same crop under light that falls off from left to right: parchment from 245 down to 175."""
    grey = np.asarray(image.convert("L"), dtype=np.float64)
    ground = np.linspace(245, 175, grey.shape[1])[None, :].repeat(grey.shape[0], axis=0)
    lit = np.where(grey > 128, ground, grey)
    return Image.fromarray(lit.astype(np.uint8)).convert("RGB")


def _png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_otsu_s_threshold_falls_between_ink_and_ground_wherever_they_lie():
    assert 40 <= otsu_threshold(np.array([[40] * 30 + [200] * 70], dtype=np.uint8)) < 200
    # Faded ink on pale parchment: both above the middle grey.
    assert 150 <= otsu_threshold(np.array([[150] * 30 + [220] * 70], dtype=np.uint8)) < 220


class TestInk:
    def test_is_a_centred_unit_vector_of_32_by_32(self):
        vector = ink_vector(_bar())

        assert len(vector) == INK_SIDE * INK_SIDE
        assert math.isclose(math.fsum(v * v for v in vector), 1.0, rel_tol=1e-9)
        assert math.isclose(math.fsum(vector), 0.0, abs_tol=1e-9)

    def test_sees_the_same_letter_whatever_the_parchment_ink_and_light(self):
        letter = ink_vector(_bar())

        assert ink_vector(_bar(ground=(200, 185, 150), ink=(110, 95, 80))) == letter
        assert ink_vector(_bar(ink=(170, 155, 135))) == letter  # faded
        assert ink_vector(_lit_unevenly(_bar())) == letter
        # Grey pixels see the light as part of the letter.
        assert _cos(pixel_vector(_bar()), pixel_vector(_lit_unevenly(_bar()))) < 0.99

    def test_tells_one_shape_from_another(self):
        ring = Image.new("RGB", (20, 60), PARCHMENT)
        ImageDraw.Draw(ring).ellipse((2, 6, 18, 54), outline=INK, width=4)

        assert _cos(ink_vector(_bar()), ink_vector(ring)) < 0.5

    def test_pads_a_tall_crop_in_its_ground(self):
        # The top row of the square is padding and the crop's own top edge, all ground.
        crop = Image.new("RGB", (20, 60), PARCHMENT)
        ImageDraw.Draw(crop).rectangle((8, 20, 12, 40), fill=INK)

        assert len({round(v, 9) for v in ink_vector(crop)[:INK_SIDE]}) == 1

    def test_a_blank_crop_matches_nothing(self):
        assert ink_vector(Image.new("RGB", (10, 10), PARCHMENT)) == [0.0] * (INK_SIDE * INK_SIDE)


class TestHog:
    def test_is_a_unit_vector_of_7_by_7_blocks_of_4_cells_by_9_bins(self):
        vector = hog_vector(_bar())

        assert len(vector) == HOG_DIMENSIONS == 7 * 7 * 4 * 9
        assert math.isclose(math.fsum(v * v for v in vector), 1.0, rel_tol=1e-9)

    def test_records_which_way_the_strokes_run(self):
        upright = _bar(width=60, height=60, left=28)
        lying = upright.rotate(90)

        assert _cos(hog_vector(upright), hog_vector(lying)) < 0.5

    def test_counts_both_edges_of_a_stroke_as_one_direction(self):
        # A stroke's left edge goes dark-to-light and its right edge light-to-dark.
        # Unsigned gradients put the two in one bin, so a pale stroke on a dark
        # ground reads as the same stroke.
        bar = _bar()

        assert _cos(hog_vector(bar), hog_vector(ImageOps.invert(bar))) > 0.99

    def test_shrugs_off_a_small_shift_and_the_light(self):
        letter = hog_vector(_bar())

        assert _cos(letter, hog_vector(_bar(left=9))) > 0.9
        assert _cos(letter, hog_vector(_bar(ground=(200, 185, 150), ink=(110, 95, 80)))) > 0.99

    def test_a_blank_crop_matches_nothing(self):
        assert hog_vector(Image.new("RGB", (10, 10), PARCHMENT)) == [0.0] * HOG_DIMENSIONS


@pytest.mark.parametrize(
    ("provider", "describe", "name", "version", "dimensions"),
    [
        (InkProvider, ink_vector, "ink", "otsu-32-1", 1024),
        (HogProvider, hog_vector, "hog", "48px-6cell-9bin-1", 1764),
    ],
)
def test_returns_one_vector_per_image_in_order(provider, describe, name, version, dimensions):
    images = [_png(_bar()), _png(_bar(left=2))]

    result = provider().run(InferenceRequest(task="W1.2", inputs={"images": images}))

    assert result.output == {"vectors": [describe(_bar()), describe(_bar(left=2))], "dimensions": dimensions}
    assert (result.model_name, result.model_version, result.cost_micros) == (name, version, 0)
    assert result.prompt_hash == content_digest(images)


@pytest.mark.parametrize("provider", [InkProvider, HogProvider])
@pytest.mark.parametrize(
    ("images", "message"),
    [
        ([], "non-empty list"),
        ([7], "non-empty list"),
        (["not base64!"], "Image 0"),
        ([_png(_bar()), "aGVsbG8="], "Image 1"),
    ],
)
def test_refuses_what_it_cannot_read(provider, images, message):
    with pytest.raises(ProviderError, match=message):
        provider().run(InferenceRequest(task="W1.2", inputs={"images": images}))


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["ink", "hog"])
def test_is_self_hosted_and_runs_through_the_ledger(settings, name):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = False
    images = [_png(_bar())]
    service = InferenceService()

    job = service.submit(task="W1.2", provider=name, inputs={"images": images}, dispatch=False)
    job = service.run(job.pk, inputs={"images": images})

    assert resolve_provider(name).hosted is False
    assert (job.status, job.model_name, job.cost_micros) == (MLJob.Status.SUCCEEDED, name, 0)

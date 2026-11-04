"""The raw-pixel baseline, `pixels`: shrunken grey crops as unit vectors."""

import base64
import io
import math

from PIL import Image, ImageDraw
import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, content_digest, resolve_provider
from apps.ml.providers.pixels import SIDE, PixelProvider, pixel_vector
from apps.ml.services import InferenceService

PARCHMENT = (232, 220, 190)
INK = (40, 30, 20)


def _bar(width=20, height=60, *, x=None) -> Image.Image:
    image = Image.new("RGB", (width, height), PARCHMENT)
    left = width // 2 - 2 if x is None else x
    ImageDraw.Draw(image).rectangle((left, 4, left + 4, height - 4), fill=INK)
    return image


def _png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_a_crop_becomes_a_centred_unit_vector_of_16_by_16():
    vector = pixel_vector(_bar())

    assert len(vector) == SIDE * SIDE
    assert math.isclose(math.fsum(value * value for value in vector), 1.0, rel_tol=1e-9)
    assert math.isclose(math.fsum(vector), 0.0, abs_tol=1e-9)


def test_the_padding_is_the_crop_s_own_edge_colour():
    # A tall crop is padded left and right. Its top row is all parchment, so in
    # parchment-coloured padding the whole row reads as one value; black
    # padding would read as ink on either side.
    crop = Image.new("RGB", (20, 60), PARCHMENT)
    ImageDraw.Draw(crop).rectangle((8, 20, 12, 40), fill=INK)
    top_row = pixel_vector(crop)[:SIDE]

    assert len({round(value, 9) for value in top_row}) == 1


def test_it_is_blind_to_brightness_and_contrast_but_not_to_shape():
    bar = pixel_vector(_bar())
    faded = Image.eval(_bar(), lambda value: 60 + value // 2)
    ring = Image.new("RGB", (20, 60), PARCHMENT)
    ImageDraw.Draw(ring).ellipse((2, 6, 18, 54), outline=INK, width=4)

    assert _cos(bar, pixel_vector(faded)) > 0.99
    assert _cos(bar, pixel_vector(ring)) < 0.5


def test_a_blank_crop_matches_nothing():
    assert pixel_vector(Image.new("RGB", (10, 10), PARCHMENT)) == [0.0] * (SIDE * SIDE)


def test_returns_one_vector_per_image_in_order():
    images = [_png(_bar()), _png(Image.new("RGB", (10, 10), PARCHMENT))]

    result = PixelProvider().run(InferenceRequest(task="W1.2", inputs={"images": images}))

    assert result.output["dimensions"] == SIDE * SIDE
    assert result.output["vectors"] == [pixel_vector(_bar()), [0.0] * (SIDE * SIDE)]
    assert (result.model_name, result.model_version, result.cost_micros) == ("raw-pixels", "16x16-grey-1", 0)
    assert result.prompt_hash == content_digest(images)


@pytest.mark.parametrize(
    ("images", "message"),
    [
        ([], "non-empty list"),
        ([7], "non-empty list"),
        (["not base64!"], "Image 0"),
        ([_png(_bar()), "aGVsbG8="], "Image 1"),
    ],
)
def test_refuses_what_it_cannot_read(images, message):
    with pytest.raises(ProviderError, match=message):
        PixelProvider().run(InferenceRequest(task="W1.2", inputs={"images": images}))


@pytest.mark.django_db
def test_is_self_hosted_and_runs_through_the_ledger(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = False
    images = [_png(_bar())]
    service = InferenceService()

    job = service.submit(task="W1.2", provider="pixels", inputs={"images": images}, dispatch=False)
    job = service.run(job.pk, inputs={"images": images})

    assert resolve_provider("pixels").hosted is False
    assert (job.status, job.model_name, job.cost_micros) == (MLJob.Status.SUCCEEDED, "raw-pixels", 0)

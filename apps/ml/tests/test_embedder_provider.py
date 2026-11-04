"""The self-hosted glyph encoder, `dinov2`, as the platform reaches it.

The HTTP call is mocked: the service itself is checked against its weights when
its image is built (`embedder/selftest.py`). What is pinned here is the
contract — what is sent, what is accepted back, and that a bad answer is never
paired with the wrong glyph.
"""

import io
import json
from unittest import mock
import urllib.error

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, content_digest, resolve_provider
from apps.ml.providers.embedder import DEFAULT_TIMEOUT, EmbedderProvider
from apps.ml.services import InferenceService

IMAGES = ["aW1hZ2Ugb25l", "aW1hZ2UgdHdv"]


def _answer(*, vectors=None, dimensions=3, model="facebook/dinov2-small", revision="ed25f3a3"):
    body = {
        "model": model,
        "revision": revision,
        "dimensions": dimensions,
        "vectors": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]] if vectors is None else vectors,
    }
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return response


@pytest.fixture
def configured(settings):
    settings.ML_EMBEDDER_URL = "http://embedder:8080/"
    return settings


def _run(images=IMAGES, params=None):
    return EmbedderProvider().run(InferenceRequest(task="W1.2", inputs={"images": images}, params=params or {}))


def test_it_is_registered_as_self_hosted():
    registration = resolve_provider("dinov2")

    assert registration.hosted is False
    assert registration.factory is EmbedderProvider


def test_posts_the_crops_and_returns_one_vector_per_crop(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer()) as urlopen:
        result = _run()

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://embedder:8080/embed"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"images": IMAGES}
    assert urlopen.call_args.kwargs == {"timeout": DEFAULT_TIMEOUT}
    assert result.output == {"vectors": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "dimensions": 3}
    assert (result.model_name, result.model_version) == ("facebook/dinov2-small", "ed25f3a3")
    assert (result.cost_micros, result.prompt_hash) == (0, content_digest(IMAGES))


def test_a_caller_can_shorten_the_wait(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer()) as urlopen:
        _run(params={"timeout_seconds": 5})

    assert urlopen.call_args.kwargs == {"timeout": 5.0}


def test_refuses_to_run_unconfigured(settings):
    settings.ML_EMBEDDER_URL = ""

    with mock.patch("urllib.request.urlopen") as urlopen, pytest.raises(ProviderError, match="ML_EMBEDDER_URL"):
        _run()
    urlopen.assert_not_called()


@pytest.mark.parametrize("images", [[], "aW1hZ2U=", [1, 2], None])
def test_refuses_inputs_that_are_not_a_list_of_images(configured, images):
    with mock.patch("urllib.request.urlopen") as urlopen, pytest.raises(ProviderError, match="non-empty list"):
        _run(images=images)
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (_answer(vectors=[[1.0, 0.0, 0.0]]), "returned 1 vectors for 2 images"),
        (_answer(vectors=[[1.0, 0.0, 0.0], [0.0, 1.0]]), "Vector 1 is not 3 numbers long"),
        (_answer(vectors=[[1.0, 0.0, 0.0], [0.0, "x", 0.0]]), "Vector 1 holds something that is not a number"),
        (_answer(vectors={"a": 1}), "returned no vectors for 2 images"),
        (_answer(dimensions=None), "did not say how long"),
    ],
)
def test_refuses_an_answer_that_does_not_fit_the_crops(configured, answer, message):
    with mock.patch("urllib.request.urlopen", return_value=answer), pytest.raises(ProviderError, match=message):
        _run()


def test_passes_on_why_the_service_refused(configured):
    refusal = urllib.error.HTTPError(
        "http://embedder:8080/embed", 400, "Bad Request", {}, io.BytesIO(b'{"detail": "Image 1 is empty."}')
    )

    with mock.patch("urllib.request.urlopen", side_effect=refusal), pytest.raises(ProviderError) as error:
        _run()

    assert str(error.value) == 'The encoder refused the request (400): {"detail": "Image 1 is empty."}'


@pytest.mark.parametrize("failure", [urllib.error.URLError("Connection refused"), TimeoutError("timed out")])
def test_an_unreachable_service_is_a_provider_error(configured, failure):
    with mock.patch("urllib.request.urlopen", side_effect=failure), pytest.raises(ProviderError, match="reached"):
        _run()


def test_an_answer_that_is_not_json_is_a_provider_error(configured):
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = b"<html>bad gateway</html>"

    with mock.patch("urllib.request.urlopen", return_value=response), pytest.raises(ProviderError, match="no JSON"):
        _run()


@pytest.mark.django_db
def test_runs_through_the_ledger_without_the_hosted_switch(configured):
    configured.ML_INFERENCE_ENABLED = True
    configured.ML_HOSTED_PROVIDERS_ENABLED = False
    service = InferenceService()

    with mock.patch("urllib.request.urlopen", return_value=_answer()):
        job = service.submit(task="W1.2", provider="dinov2", inputs={"images": IMAGES}, dispatch=False)
        job = service.run(job.pk, inputs={"images": IMAGES})

    assert job.status == MLJob.Status.SUCCEEDED
    assert (job.provider, job.model_name, job.model_version, job.cost_micros) == (
        "dinov2",
        "facebook/dinov2-small",
        "ed25f3a3",
        0,
    )
    assert job._output["vectors"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


@pytest.mark.django_db
def test_does_not_run_while_inference_is_off(configured):
    configured.ML_INFERENCE_ENABLED = False

    with mock.patch("urllib.request.urlopen") as urlopen:
        job = InferenceService().submit(task="W1.2", provider="dinov2", inputs={"images": IMAGES}, dispatch=False)

    assert job.status == MLJob.Status.REFUSED
    urlopen.assert_not_called()

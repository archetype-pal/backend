"""The self-hosted reader, `kraken`, as the platform reaches it.

The HTTP call is mocked: the service itself is checked against its model when
its image is built (`htr/selftest.py`). What is pinned here is the contract:
what is sent, what is accepted back, and that the HTR harness reads the answer
as it reads a hosted model's.
"""

import io
import json
from unittest import mock
import urllib.error

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, content_digest, resolve_provider
from apps.ml.providers.htr_service import DEFAULT_TIMEOUT, HtrServiceProvider
from apps.ml.services import InferenceService
from apps.vision.services import htr

PAGE = "cGFnZSBvbmU="
DATA_URL = f"data:image/jpeg;base64,{PAGE}"
SHA = "d1c1fd46af4003b8cf9b18c7049f93f48a8df07f2cbdf29c1d407affe9e251bd"
LINES = [
    {"text": "Alex̾ dei gr̃a rex scott̾", "box": [102, 88, 1210, 46]},
    {"text": "concessisse ⁊ hac carta nr̃a", "box": [98, 140, 1190, 44]},
]


def _answer(*, lines=None, model="CATMuS Medieval 1.5.0", revision=SHA):
    body = {"model": model, "revision": revision, "segmenter": "kraken blla"}
    body["lines"] = LINES if lines is None else lines
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return response


@pytest.fixture
def configured(settings):
    settings.ML_HTR_URL = "http://htr:8080/"
    return settings


def _run(images=None, params=None):
    inputs = {"images": [DATA_URL] if images is None else images, "prompt": "Transcribe this charter."}
    return HtrServiceProvider().run(InferenceRequest(task="W1.4", inputs=inputs, params=params or {}))


def test_it_is_registered_as_self_hosted():
    registration = resolve_provider("kraken")

    assert registration.hosted is False
    assert registration.factory is HtrServiceProvider


def test_posts_the_page_and_answers_with_its_lines_as_a_hosted_model_would(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer()) as urlopen:
        result = _run()

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://htr:8080/read"
    assert request.get_method() == "POST"
    # The page only: the data URL's prefix is dropped, and the prompt is not sent.
    assert json.loads(request.data) == {"image": PAGE}
    assert urlopen.call_args.kwargs == {"timeout": DEFAULT_TIMEOUT}
    assert json.loads(result.output["text"]) == {"lines": [line["text"] for line in LINES], "notes": ""}
    assert result.output["boxes"] == [line["box"] for line in LINES]
    assert (result.model_name, result.model_version) == ("CATMuS Medieval 1.5.0", SHA)
    assert (result.cost_micros, result.prompt_hash) == (0, content_digest([PAGE]))
    assert htr.parse(result.output["text"]) == {"lines": [line["text"] for line in LINES], "notes": ""}


def test_sends_bare_base64_as_it_is(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer()) as urlopen:
        _run(images=[PAGE])

    assert json.loads(urlopen.call_args.args[0].data) == {"image": PAGE}


def test_a_caller_can_shorten_the_wait(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer()) as urlopen:
        _run(params={"timeout_seconds": 5})

    assert urlopen.call_args.kwargs == {"timeout": 5.0}


def test_refuses_to_run_unconfigured(settings):
    settings.ML_HTR_URL = ""

    with mock.patch("urllib.request.urlopen") as urlopen, pytest.raises(ProviderError, match="ML_HTR_URL"):
        _run()
    urlopen.assert_not_called()


@pytest.mark.parametrize("images", [[], DATA_URL, [DATA_URL, DATA_URL], [1], None])
def test_refuses_anything_but_one_page(configured, images):
    with mock.patch("urllib.request.urlopen") as urlopen, pytest.raises(ProviderError, match="exactly one page"):
        HtrServiceProvider().run(InferenceRequest(task="W1.4", inputs={"images": images}, params={}))
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ({"text": "a"}, "no list of lines"),
        (["a line"], "Line 0 has no reading"),
        ([LINES[0], {"box": [1, 2, 3, 4]}], "Line 1 has no reading"),
        ([LINES[0], {"text": "a", "box": [1, 2, 3]}], "Line 1 has no box of four numbers"),
        ([{"text": "a", "box": [1, 2, 3, "4"]}], "Line 0 has no box of four numbers"),
        ([{"text": "a"}], "Line 0 has no box of four numbers"),
    ],
)
def test_refuses_an_answer_that_is_not_lines_with_boxes(configured, lines, message):
    with mock.patch("urllib.request.urlopen", return_value=_answer(lines=lines)), pytest.raises(ProviderError) as error:
        _run()

    assert message in str(error.value)


def test_a_page_with_no_lines_is_an_answer_the_harness_calls_empty(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer(lines=[])):
        result = _run()

    assert result.output["boxes"] == []
    with pytest.raises(ValueError, match="no lines"):
        htr.parse(result.output["text"])


def test_passes_on_why_the_service_refused(configured):
    refusal = urllib.error.HTTPError(
        "http://htr:8080/read", 400, "Bad Request", {}, io.BytesIO(b'{"detail": "The image is empty."}')
    )

    with mock.patch("urllib.request.urlopen", side_effect=refusal), pytest.raises(ProviderError) as error:
        _run()

    assert str(error.value) == 'The reader refused the request (400): {"detail": "The image is empty."}'


@pytest.mark.parametrize("failure", [urllib.error.URLError("Connection refused"), TimeoutError("timed out")])
def test_an_unreachable_service_is_a_provider_error(configured, failure):
    with mock.patch("urllib.request.urlopen", side_effect=failure), pytest.raises(ProviderError, match="reached"):
        _run()


@pytest.mark.parametrize(("body", "message"), [(b"<html>bad gateway</html>", "no JSON"), (b"[]", "not a JSON object")])
def test_an_answer_that_is_not_a_json_object_is_a_provider_error(configured, body, message):
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = body

    with mock.patch("urllib.request.urlopen", return_value=response), pytest.raises(ProviderError, match=message):
        _run()


@pytest.mark.django_db
def test_runs_through_the_ledger_without_the_hosted_switch(configured):
    configured.ML_INFERENCE_ENABLED = True
    configured.ML_HOSTED_PROVIDERS_ENABLED = False
    service = InferenceService()
    inputs = {"images": [DATA_URL]}

    with mock.patch("urllib.request.urlopen", return_value=_answer()):
        job = service.submit(task="W1.4", provider="kraken", inputs=inputs, dispatch=False)
        job = service.run(job.pk, inputs=inputs)

    assert job.status == MLJob.Status.SUCCEEDED
    assert (job.provider, job.model_name, job.model_version, job.cost_micros) == (
        "kraken",
        "CATMuS Medieval 1.5.0",
        SHA,
        0,
    )
    assert json.loads(job._output_text)["lines"][0] == LINES[0]["text"]


@pytest.mark.django_db
def test_does_not_run_while_inference_is_off(configured):
    configured.ML_INFERENCE_ENABLED = False

    with mock.patch("urllib.request.urlopen") as urlopen:
        job = InferenceService().submit(task="W1.4", provider="kraken", inputs={"images": [DATA_URL]}, dispatch=False)

    assert job.status == MLJob.Status.REFUSED
    urlopen.assert_not_called()

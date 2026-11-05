"""The self-hosted letter models, `letters`, as the platform reaches them (W1.1).

The HTTP call is mocked, as it is for the reader (`test_htr_service_provider`).
What is pinned here is the contract: what is sent, which answers are accepted,
and that the ledger names the letter models' weights rather than Kraken's.
"""

import io
import json
from unittest import mock
import urllib.error

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, content_digest, resolve_provider
from apps.ml.providers.htr_service import DEFAULT_TIMEOUT, HtrLettersProvider
from apps.ml.services import InferenceService

PAGE = "cGFnZSBvbmU="
DATA_URL = f"data:image/jpeg;base64,{PAGE}"
LETTERS_SHA = "7" * 64
LETTERS = [
    {
        "read": "ſ",
        "read_confidence": 0.98,
        "line": 0,
        "box": [102.5, 88.0, 31.0, 70.5],
        "fit": 0.81,
        "character": "s",
        "allograph": "long",
        "probability": 0.93,
    },
    {
        "read": "⁊",
        "read_confidence": 0.9,
        "line": 1,
        "box": [400, 150, 40, 42],
        "fit": 0.7,
        "character": "7",
        "allograph": "7",
        "probability": 0.99,
    },
]


def _answer(*, found=None, models=None, width=2000, height=1500):
    body = {
        "model": "CATMuS Medieval 1.5.0",
        "revision": "d1c1" * 16,
        "segmenter": "kraken blla",
        "letter_models": {"name": "letters", "revision": LETTERS_SHA, "release": "local-2026-11-04"}
        if models is None
        else models,
        "width": width,
        "height": height,
        "letters": LETTERS if found is None else found,
    }
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return response


@pytest.fixture
def configured(settings):
    settings.ML_HTR_URL = "http://htr:8080/"
    return settings


def _run(images=None):
    inputs = {"images": [DATA_URL] if images is None else images}
    return HtrLettersProvider().run(InferenceRequest(task="W1.1", inputs=inputs, params={}))


def test_it_is_registered_as_self_hosted():
    registration = resolve_provider("letters")

    assert registration.hosted is False
    assert registration.factory is HtrLettersProvider


def test_posts_the_page_and_answers_with_its_letters_and_the_size_it_read(configured):
    with mock.patch("urllib.request.urlopen", return_value=_answer()) as urlopen:
        result = _run()

    request = urlopen.call_args.args[0]
    assert request.full_url == "http://htr:8080/letters"
    assert json.loads(request.data) == {"image": PAGE}
    assert urlopen.call_args.kwargs == {"timeout": DEFAULT_TIMEOUT}
    assert result.output == {"text": "", "letters": LETTERS, "width": 2000, "height": 1500}
    assert (result.model_name, result.model_version) == ("letters on CATMuS Medieval 1.5.0", LETTERS_SHA)
    assert (result.cost_micros, result.prompt_hash) == (0, content_digest([PAGE]))


def test_refuses_anything_but_one_page(configured):
    with mock.patch("urllib.request.urlopen") as urlopen, pytest.raises(ProviderError, match="exactly one page"):
        _run(images=[DATA_URL, DATA_URL])
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"models": {}}, "did not name the letter models"),
        ({"models": {"name": "letters"}}, "did not name the letter models"),
        ({"width": None}, "how large the page"),
        ({"height": 0}, "how large the page"),
        ({"found": {"box": [1, 2, 3, 4]}}, "no list of letters"),
        ({"found": ["a"]}, "Letter 0 is not an object"),
        ({"found": [LETTERS[0], {**LETTERS[1], "box": [1, 2, 3]}]}, "Letter 1 has no box of four numbers"),
        ({"found": [{**LETTERS[0], "box": [1, 2, 3, True]}]}, "Letter 0 has no box of four numbers"),
        ({"found": [{**LETTERS[0], "fit": None}]}, "Letter 0 has no fit or probability"),
        ({"found": [{**LETTERS[0], "probability": "high"}]}, "Letter 0 has no fit or probability"),
        ({"found": [{**LETTERS[0], "allograph": None}]}, "Letter 0 names no allograph"),
    ],
)
def test_refuses_an_answer_that_is_not_letters_with_boxes_and_allographs(configured, answer, message):
    with mock.patch("urllib.request.urlopen", return_value=_answer(**answer)), pytest.raises(ProviderError) as error:
        _run()

    assert message in str(error.value)


def test_passes_on_that_no_letter_models_are_installed(configured):
    refusal = urllib.error.HTTPError(
        "http://htr:8080/letters",
        503,
        "Service Unavailable",
        {},
        io.BytesIO(b'{"detail": "No letter models are installed in /models/letters; see train_letters.py."}'),
    )

    with mock.patch("urllib.request.urlopen", side_effect=refusal), pytest.raises(ProviderError) as error:
        _run()

    assert "(503)" in str(error.value)
    assert "No letter models are installed" in str(error.value)


@pytest.mark.django_db
def test_runs_through_the_ledger_without_the_hosted_switch(configured):
    configured.ML_INFERENCE_ENABLED = True
    configured.ML_HOSTED_PROVIDERS_ENABLED = False
    service = InferenceService()
    inputs = {"images": [DATA_URL]}

    with mock.patch("urllib.request.urlopen", return_value=_answer()):
        job = service.submit(task="W1.1", provider="letters", inputs=inputs, dispatch=False)
        job = service.run(job.pk, inputs=inputs)

    assert job.status == MLJob.Status.SUCCEEDED
    assert (job.provider, job.model_version, job.cost_micros) == ("letters", LETTERS_SHA, 0)
    assert job._output["letters"] == LETTERS

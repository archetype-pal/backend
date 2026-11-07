"""W1.1 — one page's letters proposed by the letter models because a user asked for it.

The reader is replaced at its HTTP calls: `GET /health` says whether it has
letter models, and `POST /letters` answers as the service does (its contract
is pinned in `apps/ml/tests/test_htr_letters_provider.py`). The page is
1,000 × 750 and sent as it is.
"""

import base64
from datetime import timedelta
import io
import json
from unittest import mock

from django.urls import reverse
from django.utils import timezone
from PIL import Image
import pytest

from apps.annotations.models import GraphProposal
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.models import MLJob
from apps.ml.providers.htr_service import installed_letter_models
from apps.ml.tests.factories import MLJobFactory
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory, CharacterFactory
from apps.vision.models import LetterRequest
from apps.vision.services import page_letters

pytestmark = pytest.mark.django_db

WIDTH, HEIGHT = 1000, 750
LETTER_MODELS = {"name": "letters", "revision": "7" * 64, "release": "local-2026-11-04"}


def _jpeg() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), (230, 220, 190)).save(buffer, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _reply(body: dict) -> mock.MagicMock:
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return response


def _found(x: int, *, allograph="long", fit=0.9) -> dict:
    return {
        "read": "s",
        "read_confidence": 0.9,
        "line": 0,
        "box": [x, 100, 20, 40],
        "fit": fit,
        "character": "s",
        "allograph": allograph,
        "probability": 0.95,
    }


def _reader(*, letter_models=LETTER_MODELS, found=None, letters_status: int | None = None):
    """The reader: its health check, and its answer to `/letters`."""
    letters_body = {
        "model": "CATMuS Medieval 1.5.0",
        "revision": "d1c1" * 16,
        "letter_models": letter_models,
        "width": WIDTH,
        "height": HEIGHT,
        "letters": found if found is not None else [_found(100), _found(200), _found(300, allograph="round")],
    }

    def urlopen(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        if url.endswith("/health"):
            return _reply({"model": "CATMuS Medieval 1.5.0", "letter_models": letter_models})
        if letters_status is not None:
            import urllib.error

            raise urllib.error.HTTPError(url, letters_status, "refused", {}, io.BytesIO(b"no letter models"))
        return _reply(letters_body)

    return mock.patch("urllib.request.urlopen", side_effect=urlopen)


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = False
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    settings.ML_HTR_URL = "http://htr:8080"
    return settings


@pytest.fixture
def page():
    with (
        mock.patch("apps.vision.images.dimensions", return_value=(WIDTH, HEIGHT)),
        mock.patch("apps.vision.images.data_url", return_value=_jpeg()),
    ):
        yield


@pytest.fixture
def dispatched():
    with mock.patch("apps.vision.tasks.propose_page_letters.delay") as delay:
        yield delay


@pytest.fixture
def taxonomy():
    s = CharacterFactory(name="s")
    return {"long": AllographFactory(character=s, name="long"), "round": AllographFactory(character=s, name="round")}


def _url(image_id: int) -> str:
    return str(reverse("page-letters", kwargs={"pk": image_id}))


def _queued(image=None, **fields) -> LetterRequest:
    run: LetterRequest = LetterRequest.objects.create(item_image=image or ItemImageFactory(), **fields)
    return run


class TestAsking:
    def test_a_page_is_queued_for_the_worker_and_answered_at_once(
        self, management_client, management_user, enabled, dispatched, django_capture_on_commit_callbacks
    ):
        image = ItemImageFactory()

        with _reader(), django_capture_on_commit_callbacks(execute=True):
            response = management_client.post(_url(image.pk))

        assert response.status_code == 202
        run = LetterRequest.objects.get()
        assert response.json() | {"created": None, "updated": None} == {
            "id": run.pk,
            "item_image": image.pk,
            "status": "queued",
            "error": "",
            "requested_by": management_user.username,
            "ml_job": None,
            "found": 0,
            "proposed": 0,
            "created": None,
            "updated": None,
        }
        dispatched.assert_called_once_with(run.pk)
        assert MLJob.objects.count() == 0

    def test_nothing_is_queued_while_inference_is_switched_off(self, management_client, settings, dispatched):
        settings.ML_INFERENCE_ENABLED = False

        response = management_client.post(_url(ItemImageFactory().pk))

        assert response.status_code == 503
        assert response.json()["detail"] == page_letters.UNAVAILABLE
        assert not LetterRequest.objects.exists()

    def test_the_hosted_switch_does_not_apply(self, management_client, enabled, dispatched):
        """The letter models run on our own server: nothing is sent to a hosted provider."""
        enabled.ML_HOSTED_PROVIDERS_ENABLED = False

        with _reader():
            response = management_client.post(_url(ItemImageFactory().pk))

        assert response.status_code == 202

    @pytest.mark.parametrize(
        "reader",
        [
            pytest.param(lambda: _reader(letter_models=None), id="no letter models"),
            pytest.param(
                lambda: mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
                id="the reader does not answer",
            ),
        ],
    )
    def test_nothing_is_queued_when_the_reader_cannot_propose_letters(
        self, management_client, enabled, dispatched, reader
    ):
        with reader():
            response = management_client.post(_url(ItemImageFactory().pk))

        assert response.status_code == 503
        assert response.json()["detail"] == page_letters.NO_MODELS
        assert not LetterRequest.objects.exists()

    def test_a_spend_cap_does_not_stop_a_model_that_bills_nothing(self, management_client, enabled, dispatched):
        enabled.ML_DAILY_COST_CAP_MICROS = 1000
        MLJobFactory(cost_micros=1000)

        with _reader():
            response = management_client.post(_url(ItemImageFactory().pk))

        assert response.status_code == 202
        assert LetterRequest.objects.exists()

    def test_a_page_being_worked_on_is_not_asked_for_twice(self, management_client, enabled, dispatched):
        run = _queued(status=LetterRequest.Status.WORKING)

        with _reader():
            response = management_client.post(_url(run.item_image_id))

        assert response.status_code == 409
        assert response.json()["run"]["id"] == run.pk
        assert LetterRequest.objects.count() == 1
        dispatched.assert_not_called()

    def test_a_request_abandoned_by_its_worker_does_not_block_the_page(self, management_client, enabled, dispatched):
        stuck = _queued(status=LetterRequest.Status.WORKING)
        LetterRequest.objects.filter(pk=stuck.pk).update(
            updated=timezone.now() - page_letters.ABANDONED_AFTER - timedelta(minutes=1)
        )

        with _reader():
            response = management_client.post(_url(stuck.item_image_id))

        assert response.status_code == 202
        stuck.refresh_from_db()
        assert stuck.status == LetterRequest.Status.FAILED

    def test_the_page_follows_its_latest_request(self, management_client):
        image = ItemImageFactory()
        _queued(image, status=LetterRequest.Status.FAILED)
        latest = _queued(image, status=LetterRequest.Status.WORKING)

        assert management_client.get(_url(image.pk)).json()["id"] == latest.pk

    def test_a_page_nobody_asked_about_has_nothing_to_follow(self, management_client):
        assert management_client.get(_url(ItemImageFactory().pk)).status_code == 404

    def test_the_list_gives_the_requests_under_way(self, management_client):
        under_way = [_queued(status=LetterRequest.Status.QUEUED), _queued(status=LetterRequest.Status.WORKING)]
        _queued(status=LetterRequest.Status.PROPOSED)

        body = management_client.get(reverse("page-letters-list"), {"status": ["queued", "working"]}).json()

        assert sorted(row["id"] for row in body["results"]) == sorted(run.pk for run in under_way)


class TestTheWorker:
    def test_files_the_page_s_letters_and_records_the_job_the_queue_filters_by(self, enabled, page, taxonomy):
        image = ItemImageFactory()
        HandFactory(item_part=image.item_part)
        run = _queued(image)

        with _reader():
            run = page_letters.propose(run.pk)

        job = MLJob.objects.get()
        assert (run.status, run.found, run.proposed, run.ml_job, run.error) == ("proposed", 3, 3, job, "")
        assert set(GraphProposal.objects.values_list("ml_job", flat=True)) == {job.pk}
        assert (job.task, job.provider) == ("W1.1", "letters")

    def test_a_reader_that_refuses_fails_the_request_with_its_reason(self, enabled, page, taxonomy):
        run = _queued()

        with _reader(letters_status=503):
            run = page_letters.propose(run.pk)

        assert run.status == LetterRequest.Status.FAILED
        assert "no letter models" in run.error
        assert run.ml_job == MLJob.objects.get()
        assert not GraphProposal.objects.exists()

    def test_inference_switched_off_since_the_request_refuses_it(self, enabled, page, taxonomy):
        run = _queued()
        enabled.ML_INFERENCE_ENABLED = False

        with _reader():
            run = page_letters.propose(run.pk)

        assert run.status == LetterRequest.Status.REFUSED
        assert run.error.startswith("The models were not asked")

    def test_a_page_whose_image_cannot_be_fetched_fails_saying_so(self, enabled, taxonomy):
        from apps.vision.images import ImageUnavailable

        run = _queued()

        with mock.patch("apps.vision.images.dimensions", side_effect=ImageUnavailable("gone")):
            run = page_letters.propose(run.pk)

        assert (run.status, run.error) == (LetterRequest.Status.FAILED, page_letters.FAILURES["unavailable"])

    def test_a_crash_does_not_leave_the_request_working(self, enabled, page):
        run = _queued()

        with (
            mock.patch("apps.vision.services.letters.propose_page", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            page_letters.propose(run.pk)

        run.refresh_from_db()
        assert run.status == LetterRequest.Status.FAILED

    def test_a_request_already_run_is_not_run_again(self, enabled, page):
        run = _queued(status=LetterRequest.Status.PROPOSED)

        with mock.patch("apps.vision.services.letters.propose_page") as propose_page:
            page_letters.propose(run.pk)

        propose_page.assert_not_called()


def test_the_reader_s_letter_models_are_read_from_its_health_check(settings):
    settings.ML_HTR_URL = "http://htr:8080/"

    with _reader() as urlopen:
        assert installed_letter_models() == LETTER_MODELS

    assert urlopen.call_args.args[0] == "http://htr:8080/health"

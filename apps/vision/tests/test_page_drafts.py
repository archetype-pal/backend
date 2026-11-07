"""W1.4 — a page's transcription drafted by a model because a user asked for it."""

from datetime import timedelta
import json
from unittest import mock

from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
import pytest
from rest_framework.test import APIClient

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult
from apps.ml.tests.factories import MLJobFactory
from apps.users.tests.factories import UserFactory
from apps.vision.models import PageDraft
from apps.vision.services import page_drafts

pytestmark = pytest.mark.django_db

READING = json.dumps({"lines": ["Willelmus rex Scott<ex>orum</ex>", "omnibus probis hominibus"], "notes": ""})


class _Answering:
    def __init__(self, text: str = READING):
        self.text = text
        self.requests: list[InferenceRequest] = []

    def run(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        return InferenceResult(output={"text": self.text}, model_name="claude-fable-5-1", cost_micros=280000)


def _provider(provider):
    registration = mock.Mock(hosted=True, factory=lambda: provider)
    registration.name = "claude"
    return mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration)


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 10_000_000
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


@pytest.fixture
def page_image():
    with mock.patch("apps.vision.images.data_url", return_value="data:image/jpeg;base64,AAA") as fetch:
        yield fetch


@pytest.fixture
def dispatched():
    with mock.patch("apps.vision.tasks.draft_page.delay") as delay:
        yield delay


def _url(image_id: int) -> str:
    return str(reverse("page-draft", kwargs={"pk": image_id}))


def _queued(image=None, **fields) -> PageDraft:
    draft: PageDraft = PageDraft.objects.create(item_image=image or ItemImageFactory(), **fields)
    return draft


class TestAsking:
    def test_a_page_is_queued_for_the_worker_and_answered_at_once(
        self, management_client, management_user, enabled, dispatched, django_capture_on_commit_callbacks
    ):
        image = ItemImageFactory()

        with django_capture_on_commit_callbacks(execute=True):
            response = management_client.post(_url(image.pk))

        assert response.status_code == 202
        body = response.json()
        draft = PageDraft.objects.get()
        assert body["id"] == draft.pk
        assert body["item_image"] == image.pk
        assert body["status"] == "queued"
        assert body["requested_by"] == management_user.username
        assert body["image_text"] is None
        dispatched.assert_called_once_with(draft.pk)
        assert MLJob.objects.count() == 0

    def test_nothing_is_queued_while_drafting_is_switched_off(self, management_client, settings, dispatched):
        settings.ML_INFERENCE_ENABLED = True
        settings.ML_HOSTED_PROVIDERS_ENABLED = False
        image = ItemImageFactory()

        response = management_client.post(_url(image.pk))

        assert response.status_code == 503
        assert response.json()["detail"] == page_drafts.UNAVAILABLE
        assert not PageDraft.objects.exists()
        dispatched.assert_not_called()

    def test_nothing_is_queued_once_a_spend_cap_is_reached(self, management_client, enabled, dispatched):
        enabled.ML_DAILY_COST_CAP_MICROS = 1000
        MLJobFactory(cost_micros=1000)
        image = ItemImageFactory()

        response = management_client.post(_url(image.pk))

        assert response.status_code == 429
        assert "cap" in response.json()["detail"]
        assert not PageDraft.objects.exists()

    def test_a_page_with_a_transcription_is_not_drafted(self, management_client, enabled, dispatched):
        text = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="A scholar's transcription")

        response = management_client.post(_url(text.item_image_id))

        assert response.status_code == 409
        assert response.json()["image_text"] == text.pk
        assert not PageDraft.objects.exists()

    def test_a_page_with_only_a_translation_may_be_drafted(self, management_client, enabled, dispatched):
        text = ImageTextFactory(type=ImageText.Type.TRANSLATION, content="A translation")

        response = management_client.post(_url(text.item_image_id))

        assert response.status_code == 202

    def test_a_page_being_drafted_is_not_drafted_twice(self, management_client, enabled, dispatched):
        draft = _queued(status=PageDraft.Status.WORKING)

        response = management_client.post(_url(draft.item_image_id))

        assert response.status_code == 409
        assert response.json()["draft"]["id"] == draft.pk
        assert PageDraft.objects.count() == 1
        dispatched.assert_not_called()

    def test_a_draft_abandoned_long_ago_does_not_hold_the_page(self, management_client, enabled, dispatched):
        abandoned = _queued(status=PageDraft.Status.WORKING)
        PageDraft.objects.filter(pk=abandoned.pk).update(
            updated=timezone.now() - page_drafts.ABANDONED_AFTER - timedelta(minutes=1)
        )

        response = management_client.post(_url(abandoned.item_image_id))

        assert response.status_code == 202
        abandoned.refresh_from_db()
        assert abandoned.status == PageDraft.Status.FAILED
        assert abandoned.error

    def test_a_page_drafted_before_may_be_drafted_again_once_its_draft_is_gone(
        self, management_client, enabled, dispatched
    ):
        earlier = _queued(status=PageDraft.Status.FAILED, error="The model call failed.")

        response = management_client.post(_url(earlier.item_image_id))

        assert response.status_code == 202
        assert PageDraft.objects.count() == 2

    def test_only_a_superuser_may_ask(self, authenticated_client, enabled, dispatched):
        image = ItemImageFactory()

        assert authenticated_client.post(_url(image.pk)).status_code == 403
        assert APIClient().post(_url(image.pk)).status_code in (401, 403)
        assert not PageDraft.objects.exists()

    def test_an_unknown_page(self, management_client, enabled, dispatched):
        assert management_client.post(_url(999999)).status_code == 404


class TestFollowing:
    def test_the_page_answers_with_its_latest_draft(self, management_client):
        image = ItemImageFactory()
        _queued(image, status=PageDraft.Status.FAILED)
        latest = _queued(image, status=PageDraft.Status.WORKING)

        body = management_client.get(_url(image.pk)).json()

        assert body["id"] == latest.pk
        assert body["status"] == "working"

    def test_a_page_never_drafted(self, management_client):
        assert management_client.get(_url(ItemImageFactory().pk)).status_code == 404

    def test_the_drafts_under_way_are_listed_by_status(self, management_client):
        queued = _queued()
        working = _queued(status=PageDraft.Status.WORKING)
        _queued(status=PageDraft.Status.DRAFTED)
        _queued(status=PageDraft.Status.FAILED)

        body = management_client.get(reverse("page-drafts"), {"status": ["queued", "working"]}).json()

        assert {row["id"] for row in body["results"]} == {queued.pk, working.pk}

    def test_the_drafts_of_one_page(self, management_client):
        draft = _queued()
        _queued()

        body = management_client.get(reverse("page-drafts"), {"item_image": draft.item_image_id}).json()

        assert [row["id"] for row in body["results"]] == [draft.pk]

    def test_only_a_superuser_may_follow(self, authenticated_client):
        draft = _queued()

        assert authenticated_client.get(_url(draft.item_image_id)).status_code == 403
        assert authenticated_client.get(reverse("page-drafts")).status_code == 403


class TestOneAtATime:
    def test_the_database_refuses_a_second_draft_in_the_making(self):
        draft = _queued()

        with pytest.raises(IntegrityError):
            _queued(draft.item_image, status=PageDraft.Status.WORKING)

    def test_finished_drafts_do_not_count(self):
        draft = _queued(status=PageDraft.Status.FAILED)
        _queued(draft.item_image, status=PageDraft.Status.DRAFTED)

        assert _queued(draft.item_image).status == PageDraft.Status.QUEUED


class TestTheWorker:
    def test_the_page_is_read_as_measured_and_filed_as_a_draft_for_review(self, enabled, page_image):
        user = UserFactory()
        draft = _queued(requested_by=user)
        provider = _Answering()

        with _provider(provider):
            page_drafts.draft_page(draft.pk)

        draft.refresh_from_db()
        assert draft.status == PageDraft.Status.DRAFTED
        assert draft.error == ""
        text = ImageText.objects.get(item_image=draft.item_image)
        assert draft.image_text == text
        assert text.type == ImageText.Type.TRANSCRIPTION
        assert text.status == ImageText.Status.REVIEW
        assert 'resp="#machine-draft"' in text.content
        assert "Scott<ex>orum</ex>" in text.content
        assert draft.drafted_content == text.content

        inputs = provider.requests[0].inputs
        assert inputs["model"] == "claude-fable-5-1"
        assert inputs["effort"] == "high"
        assert inputs["max_tokens"] == 32000
        assert "<ex>" in inputs["system"]
        assert page_image.call_args.kwargs["size"] == 2576

        job = MLJob.objects.get()
        assert draft.ml_job == job
        assert job.task == "W1.4"
        assert job.actor == user
        assert job.cost_micros == 280000

    def test_a_drafted_page_keeps_the_draft_as_filed_after_it_is_edited(self, enabled, page_image):
        draft = _queued()
        with _provider(_Answering()):
            page_drafts.draft_page(draft.pk)
        draft.refresh_from_db()
        filed = draft.drafted_content

        ImageText.objects.filter(pk=draft.image_text_id).update(content="<div>Corrected by a reviewer</div>")

        draft.refresh_from_db()
        assert draft.drafted_content == filed

    def test_a_refusal_at_the_worker_is_recorded(self, settings, page_image):
        settings.ML_INFERENCE_ENABLED = True
        settings.ML_HOSTED_PROVIDERS_ENABLED = False
        draft = _queued()
        provider = _Answering()

        with _provider(provider):
            page_drafts.draft_page(draft.pk)

        draft.refresh_from_db()
        assert draft.status == PageDraft.Status.REFUSED
        assert "not asked" in draft.error
        assert draft.ml_job is not None
        assert provider.requests == []
        assert not ImageText.objects.exists()

    def test_an_answer_that_is_not_lines_files_nothing(self, enabled, page_image):
        draft = _queued()

        with _provider(_Answering("I cannot read this page.")):
            page_drafts.draft_page(draft.pk)

        draft.refresh_from_db()
        assert draft.status == PageDraft.Status.FAILED
        assert draft.error == page_drafts.FAILURES["unparsable"]
        assert not ImageText.objects.exists()

    def test_a_page_whose_image_cannot_be_fetched_asks_no_model(self, enabled):
        draft = _queued()
        provider = _Answering()

        with (
            _provider(provider),
            mock.patch("apps.vision.images.data_url", side_effect=page_drafts.htr.images.ImageUnavailable("no file")),
        ):
            page_drafts.draft_page(draft.pk)

        draft.refresh_from_db()
        assert draft.status == PageDraft.Status.FAILED
        assert draft.error == page_drafts.FAILURES["unavailable"]
        assert provider.requests == []
        assert not MLJob.objects.exists()

    def test_a_transcription_written_while_the_page_was_read_stands(self, enabled, page_image):
        draft = _queued()
        provider = _Answering()

        def _scholar_first(request):
            ImageTextFactory(
                item_image=draft.item_image, type=ImageText.Type.TRANSCRIPTION, content="A scholar's transcription"
            )
            return InferenceResult(output={"text": READING}, model_name="claude-fable-5-1")

        with _provider(provider), mock.patch.object(provider, "run", side_effect=_scholar_first):
            page_drafts.draft_page(draft.pk)

        draft.refresh_from_db()
        assert draft.status == PageDraft.Status.FAILED
        assert draft.error == page_drafts.WRITTEN_MEANWHILE
        assert draft.image_text is None
        assert ImageText.objects.get().content == "A scholar's transcription"

    def test_a_reading_that_crashes_does_not_leave_the_page_held(self, enabled, page_image):
        draft = _queued()
        provider = _Answering()

        with (
            _provider(provider),
            mock.patch.object(provider, "run", side_effect=RuntimeError("connection reset")),
            pytest.raises(RuntimeError),
        ):
            page_drafts.draft_page(draft.pk)

        draft.refresh_from_db()
        assert draft.status == PageDraft.Status.FAILED
        assert draft.error

    def test_a_draft_not_queued_is_not_read_again(self, enabled, page_image):
        draft = _queued(status=PageDraft.Status.DRAFTED)
        provider = _Answering()

        with _provider(provider):
            page_drafts.draft_page(draft.pk)

        assert provider.requests == []
        assert not MLJob.objects.exists()

    def test_the_task_hands_the_draft_to_the_service(self, enabled, page_image):
        from apps.vision.tasks import draft_page

        draft = _queued()

        with _provider(_Answering()):
            result = draft_page.apply(args=[draft.pk]).get()

        assert result == {"action": "page_draft", "draft": draft.pk, "status": "drafted"}

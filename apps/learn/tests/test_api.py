"""The tutor's endpoints: who may start a lesson, read it, and ask it more, and what each is told."""

from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.learn.models import TutorSession
from apps.learn.services import pictures, tutor
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.users.tests.factories import UserFactory

from .conftest import jpeg

pytestmark = pytest.mark.django_db

SESSIONS = "/api/v1/learn/sessions/"
ELSEWHERE = {"REMOTE_ADDR": "10.9.8.7"}


@pytest.fixture
def lesson_task():
    with mock.patch("apps.learn.tasks.write_lesson.delay") as delay:
        yield delay


@pytest.fixture
def answer_task():
    with mock.patch("apps.learn.tasks.answer_question.delay") as delay:
        yield delay


def _upload(name="charter.jpg", data=None):
    return SimpleUploadedFile(name, data if data is not None else jpeg(800, 600), content_type="image/jpeg")


def _ready_session(client, page, lesson_task, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(SESSIONS, {"item_image": page.pk}, format="json")
    session = TutorSession.objects.get(pk=response.data["id"])
    picture = pictures.from_upload(jpeg(800, 600))
    session.picture.save(f"{session.pk}.jpg", ContentFile(picture.jpeg), save=False)
    session.width, session.height = picture.width, picture.height
    session.status = TutorSession.Status.READY
    session.walkthrough = {"title": "A lesson"}
    session.save()
    return session


class TestStatus:
    def test_it_says_whether_the_tutor_is_on_and_what_the_requester_may_do(self, api_client, enabled):
        response = api_client.get("/api/v1/learn/")

        assert response.status_code == 200
        assert response.data["enabled"] is True
        assert response.data["uploads"] == "signed-in"
        assert response.data["may_upload"] is False
        assert response.data["languages"] == ["de", "en", "fr"]

    def test_it_is_off_until_both_switches_are_on(self, api_client, enabled):
        enabled.ML_HOSTED_PROVIDERS_ENABLED = False

        assert api_client.get("/api/v1/learn/").data["enabled"] is False

    def test_a_signed_in_requester_may_upload(self, authenticated_client):
        assert authenticated_client.get("/api/v1/learn/").data["may_upload"] is True


class TestSuggestedPages:
    def test_the_most_annotated_pages_come_first_editorial_glyphs_aside(self, api_client):
        busy, quiet = ItemImageFactory(), ItemImageFactory()
        for _ in range(3):
            GraphFactory(item_image=busy)
        GraphFactory(item_image=quiet)
        for _ in range(5):
            GraphFactory(item_image=quiet, annotation_type="editorial", allograph=None, hand=None)

        response = api_client.get("/api/v1/learn/pages/")

        assert response.status_code == 200
        assert [page["id"] for page in response.data] == [busy.pk, quiet.pk]
        assert response.data[0]["label"] == str(busy)
        assert response.data[0]["thumbnail_url"].endswith("/full/!400,400/0/default.jpg")


class TestStarting:
    def test_a_corpus_page_starts_a_lesson_for_anyone(
        self, api_client, enabled, lesson_task, django_capture_on_commit_callbacks
    ):
        page = ItemImageFactory()

        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(SESSIONS, {"item_image": page.pk, "language": "fr"}, format="json")

        assert response.status_code == 202
        session = TutorSession.objects.get(pk=response.data["id"])
        assert session.item_image == page
        assert session.language == "fr"
        assert session.status == TutorSession.Status.QUEUED
        assert session.actor is None
        assert session.requester_key
        lesson_task.assert_called_once_with(str(session.pk))
        assert response.data["page"]["id"] == page.pk
        assert response.data["can_ask"] is True

    def test_a_signed_in_student_starts_one_on_their_own_picture(
        self, authenticated_client, enabled, lesson_task, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(SESSIONS, {"picture": _upload()}, format="multipart")

        assert response.status_code == 202
        session = TutorSession.objects.get(pk=response.data["id"])
        assert session.uploaded is True
        assert session.actor is not None
        assert (session.width, session.height) == (800, 600)
        assert response.data["picture_url"].endswith(f"/api/v1/learn/sessions/{session.pk}/picture/")
        lesson_task.assert_called_once()

    def test_an_anonymous_upload_is_refused_while_uploads_need_sign_in(self, api_client, enabled, lesson_task):
        response = api_client.post(SESSIONS, {"picture": _upload()}, format="multipart")

        assert response.status_code == 403
        assert "Sign in" in response.data["detail"]
        assert not TutorSession.objects.exists()

    def test_uploads_can_be_opened_to_anyone(self, api_client, enabled, lesson_task, settings):
        settings.LEARN_UPLOADS = "anyone"

        assert api_client.post(SESSIONS, {"picture": _upload()}, format="multipart").status_code == 202

    def test_uploads_can_be_closed_to_everyone(self, authenticated_client, enabled, lesson_task, settings):
        settings.LEARN_UPLOADS = "nobody"

        response = authenticated_client.post(SESSIONS, {"picture": _upload()}, format="multipart")

        assert response.status_code == 403
        assert "corpus page" in response.data["detail"]

    def test_a_file_that_is_not_a_picture_is_refused_in_words(self, authenticated_client, enabled, lesson_task):
        response = authenticated_client.post(SESSIONS, {"picture": _upload(data=b"not a picture")}, format="multipart")

        assert response.status_code == 400
        assert response.data["detail"] == "The file is not a picture that can be read."
        assert not TutorSession.objects.exists()

    @pytest.mark.parametrize("body", [{}, "both"])
    def test_neither_or_both_of_a_page_and_a_picture_is_refused(self, authenticated_client, enabled, lesson_task, body):
        if body == "both":
            body = {"item_image": ItemImageFactory().pk, "picture": _upload()}

        assert authenticated_client.post(SESSIONS, body, format="multipart").status_code == 400

    def test_nothing_starts_while_the_tutor_is_off(self, api_client, enabled, lesson_task):
        enabled.ML_INFERENCE_ENABLED = False

        response = api_client.post(SESSIONS, {"item_image": ItemImageFactory().pk}, format="json")

        assert response.status_code == 503
        assert response.data["detail"] == tutor.UNAVAILABLE
        lesson_task.assert_not_called()

    def test_a_requester_has_a_daily_allowance(self, api_client, enabled, lesson_task, settings):
        settings.LEARN_DAILY_SESSIONS = 2
        page = ItemImageFactory()

        statuses = [api_client.post(SESSIONS, {"item_image": page.pk}, format="json").status_code for _ in range(3)]
        elsewhere = api_client.post(SESSIONS, {"item_image": page.pk}, format="json", **ELSEWHERE)

        assert statuses == [202, 202, 429]
        # Another address has its own allowance.
        assert elsewhere.status_code == 202

    def test_a_lesson_that_never_came_does_not_use_up_the_allowance(self, api_client, enabled, lesson_task, settings):
        settings.LEARN_DAILY_SESSIONS = 1
        page = ItemImageFactory()

        assert api_client.post(SESSIONS, {"item_image": page.pk}, format="json").status_code == 202
        TutorSession.objects.update(status=TutorSession.Status.FAILED)

        assert api_client.post(SESSIONS, {"item_image": page.pk}, format="json").status_code == 202


class TestReading:
    def test_anyone_with_the_link_may_read_a_lesson_but_only_its_starter_may_ask(
        self, api_client, enabled, lesson_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        mine = api_client.get(f"{SESSIONS}{session.pk}/")
        theirs = api_client.get(f"{SESSIONS}{session.pk}/", **ELSEWHERE)

        assert mine.status_code == theirs.status_code == 200
        assert mine.data["walkthrough"] == {"title": "A lesson"}
        assert mine.data["can_ask"] is True
        assert theirs.data["can_ask"] is False

    def test_what_a_lesson_cost_and_the_models_side_of_it_are_not_shown(
        self, api_client, enabled, lesson_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        data = api_client.get(f"{SESSIONS}{session.pk}/").data

        for hidden in ("cost_micros", "transcript", "requester_key", "actor", "setup", "seen_glyphs"):
            assert hidden not in data

    @pytest.mark.parametrize("pk", ["not-a-uuid", "6f1c1d1e-0000-4000-8000-000000000000"])
    def test_a_session_that_does_not_exist_is_not_found(self, api_client, pk):
        assert api_client.get(f"{SESSIONS}{pk}/").status_code == 404
        assert api_client.get(f"{SESSIONS}{pk}/picture/").status_code == 404

    def test_the_picture_is_served_as_the_tutor_saw_it_and_kept_private(
        self, api_client, enabled, lesson_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        response = api_client.get(f"{SESSIONS}{session.pk}/picture/")

        assert response.status_code == 200
        assert response["Content-Type"] == "image/jpeg"
        assert response["Cache-Control"] == "private, max-age=86400"
        with session.picture.open("rb") as handle:
            assert b"".join(response.streaming_content) == handle.read()

    def test_a_picture_not_yet_fetched_is_not_found(self, api_client, enabled, lesson_task):
        session = TutorSession.objects.create(item_image=ItemImageFactory())

        assert api_client.get(f"{SESSIONS}{session.pk}/picture/").status_code == 404


class TestAsking:
    def _ask(self, client, session, question="What is this letter?", **extra):
        return client.post(f"{SESSIONS}{session.pk}/questions/", {"question": question}, format="json", **extra)

    def test_the_starter_asks_and_the_tutor_goes_to_work(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        with django_capture_on_commit_callbacks(execute=True):
            response = self._ask(api_client, session)

        assert response.status_code == 202
        assert response.data["status"] == TutorSession.Status.WORKING
        assert response.data["messages"][-1]["role"] == "student"
        assert response.data["messages"][-1]["text"] == "What is this letter?"
        answer_task.assert_called_once_with(str(session.pk))

    def test_someone_else_may_not_ask(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        response = self._ask(api_client, session, **ELSEWHERE)

        assert response.status_code == 403
        answer_task.assert_not_called()

    def test_a_signed_in_starter_is_known_by_their_account_not_their_address(
        self, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks
    ):
        from rest_framework.test import APIClient

        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        session = _ready_session(client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)
        stranger = APIClient()

        assert self._ask(stranger, session).status_code == 403
        assert self._ask(client, session, **ELSEWHERE).status_code == 202

    def test_one_question_at_a_time(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        assert self._ask(api_client, session).status_code == 202
        assert self._ask(api_client, session).status_code == 409

    def test_a_lesson_that_did_not_finish_takes_no_questions(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)
        session.status = TutorSession.Status.FAILED
        session.save()

        assert self._ask(api_client, session).status_code == 400

    def test_a_lesson_takes_a_limited_number_of_questions(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks, settings
    ):
        settings.LEARN_QUESTIONS_PER_SESSION = 1
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)
        assert self._ask(api_client, session).status_code == 202
        session.refresh_from_db()
        session.status = TutorSession.Status.READY
        session.save()

        response = self._ask(api_client, session)

        assert response.status_code == 429
        assert response.data["code"] == "lesson_questions"
        assert api_client.get(f"{SESSIONS}{session.pk}/").data["questions_left"] == 0

    @pytest.mark.parametrize("question", ["", "   ", "x" * 2001])
    def test_an_empty_or_overlong_question_is_refused(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks, question
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)

        assert self._ask(api_client, session, question).status_code == 400

    def test_no_question_is_taken_while_the_tutor_is_off(
        self, api_client, enabled, lesson_task, answer_task, django_capture_on_commit_callbacks
    ):
        session = _ready_session(api_client, ItemImageFactory(), lesson_task, django_capture_on_commit_callbacks)
        enabled.ML_INFERENCE_ENABLED = False

        assert self._ask(api_client, session).status_code == 503

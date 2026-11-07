"""The tutor's loop: the conversation it keeps, the lesson it settles, and how it stops.

A scripted provider stands in for the model. What is pinned is never what a
model says: it is that the conversation only grows, that every picture goes
back as the bytes the tutor first saw, that what reaches the student is kept
to the picture and to glyphs a tool returned, and that every way of stopping
leaves the session in a state the page can show.
"""

import base64
import copy
import json
from unittest import mock

from django.core.files.base import ContentFile
import pytest

from apps.annotations.tests.factories import GraphFactory
from apps.learn.models import TutorSession, picture_storage
from apps.learn.services import pictures, tools, tutor
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.ml.models import MLJob
from apps.ml.providers import ProviderError
from apps.symbols_structure.tests.factories import AllographFactory
from apps.vision import images

from .conftest import call, jpeg, ring, stub, turn

pytestmark = pytest.mark.django_db

BOX = {"x": 10, "y": 10, "width": 40, "height": 60}


def uploaded(**fields) -> TutorSession:
    picture = pictures.from_upload(jpeg(800, 600))
    session = TutorSession(uploaded=True, requester_key="key", **fields)
    session.picture.save(f"{session.pk}.jpg", ContentFile(picture.jpeg), save=False)
    session.width, session.height = picture.width, picture.height
    session.save()
    return session


def lesson(**overrides):
    value = {
        "title": "Reading a charter hand",
        "overview": "A charter hand of the late twelfth century.",
        "script": {"name": "Protogothic charter minuscule", "date": "c. 1170-1200", "reasons": ["a round d"]},
        "steps": [
            {
                "title": "The long s",
                "explanation": "Its shaft descends below the line.",
                "boxes": [{**BOX, "label": "long s"}],
                "character": "s",
                "allograph_id": None,
                "look_for": ["the shaft descends below the line"],
                "example_glyph_ids": [],
            }
        ],
        "practice": {
            "instructions": "Read the first line.",
            "box": {"x": 0, "y": 0, "width": 400, "height": 50},
            "reading": "Dauid rex",
            "note": "My own reading.",
        },
    }
    value.update(overrides)
    return value


def look(call_id="toolu_look", reason="to read line 1"):
    return call(tools.LOOK_CLOSER, {"reason": reason, "box": {"x": 0, "y": 0, "width": 200, "height": 100}}, call_id)


def present(value=None, call_id="toolu_present"):
    return call(tools.PRESENT_WALKTHROUGH, value or lesson(), call_id)


def write(session, turns):
    provider, patched = stub(turns)
    with patched:
        tutor.write_lesson(session.pk)
    session.refresh_from_db()
    return provider


def _messages(request):
    return request.inputs["messages"]


def _last_results(request):
    return [block for block in _messages(request)[-1]["content"] if block["type"] == "tool_result"]


@pytest.fixture
def ready(enabled):
    """A session whose lesson is written, waiting on a question."""
    session = uploaded()
    write(session, [turn(present())])
    session.messages = [{"role": "student", "text": "What is the third letter?", "at": "now"}]
    session.status = TutorSession.Status.WORKING
    session.save()
    return session


def answer(session, turns):
    provider, patched = stub(turns)
    with patched:
        tutor.answer(session.pk)
    session.refresh_from_db()
    return provider


class TestWritingTheLesson:
    def test_a_lesson_is_written_after_a_closer_look(self, enabled):
        session = uploaded()

        write(session, [turn(look()), turn(present())])

        assert session.status == TutorSession.Status.READY
        assert session.error == ""
        assert session.walkthrough["title"] == "Reading a charter hand"
        assert session.walkthrough["steps"][0]["boxes"] == [{**BOX, "label": "long s"}]
        assert session.turns == 2
        assert session.cost_micros == 22
        assert [line["text"] for line in session.progress] == [
            "Looking at the picture",
            "Looking closer: to read line 1",
        ]
        assert MLJob.objects.filter(task=tutor.TASK, status=MLJob.Status.SUCCEEDED).count() == 2

    def test_the_conversation_only_grows(self, enabled):
        provider = write(uploaded(), [turn(look("toolu_1")), turn(look("toolu_2")), turn(present())])

        first, second, third = (_messages(request) for request in provider.requests)
        assert second[: len(first)] == first
        assert third[: len(second)] == second
        assert len({str(request.inputs["system"]) for request in provider.requests}) == 1
        assert all(request.inputs["tools"] == provider.requests[0].inputs["tools"] for request in provider.requests)

    def test_the_last_turn_is_answered_so_that_a_question_can_follow_it(self, enabled):
        session = uploaded()

        write(session, [turn(present())])

        assert [entry["role"] for entry in session.transcript] == ["user", "assistant", "user"]
        (result,) = session.transcript[-1]["content"]
        assert result == {"type": "tool_result", "tool_use_id": "toolu_present", "content": "Shown to the student."}

    def test_the_assistants_turns_are_kept_as_they_came_thinking_and_all(self, enabled):
        session = uploaded()
        first = turn(look())

        write(session, [first, turn(present())])

        assert session.transcript[1] == {"role": "assistant", "content": first["content"]}

    def test_the_picture_is_stored_once_and_sent_as_its_bytes(self, enabled):
        session = uploaded()

        provider = write(session, [turn(present())])

        stored = session.transcript[0]["content"][0]
        assert stored == {"type": "image", "source": {"type": "stored", "path": session.picture.name}}
        with picture_storage.open(session.picture.name, "rb") as handle:
            data = base64.b64encode(handle.read()).decode()
        sent = _messages(provider.requests[0])[0]["content"][0]
        assert sent == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}

    def test_a_closer_look_is_stored_and_resent_byte_for_byte(self, enabled):
        session = uploaded()

        provider = write(session, [turn(look()), turn(present())])

        (result,) = session.transcript[2]["content"]
        caption, stored, text = result["content"]
        assert caption["type"] == text["type"] == "text"
        path = stored["source"]["path"]
        assert path.startswith(f"sessions/{session.pk}/look_closer-")
        with picture_storage.open(path, "rb") as handle:
            data = base64.b64encode(handle.read()).decode()
        (sent,) = _last_results(provider.requests[1])
        assert sent["content"][1]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": data}

    def test_the_first_message_describes_the_picture_and_names_the_language(self, enabled):
        session = uploaded(language="de")

        provider = write(session, [turn(present())])

        intro = _messages(provider.requests[0])[0]["content"][1]["text"]
        assert "800 by 600 pixels" in intro
        assert "the student's own picture" in intro
        assert intro.endswith("Write the lesson in German.")

    def test_the_session_keeps_the_model_prompt_and_tools_it_started_with(self, enabled, settings):
        settings.LEARN_TUTOR_MODEL = "claude-opus-5-5"
        settings.LEARN_TUTOR_EFFORT = "max"
        form = AllographFactory(name="long")
        session = uploaded()

        provider = write(session, [turn(present())])

        assert session.setup["model"] == "claude-opus-5-5"
        assert session.setup["system"].startswith(tutor.SYSTEM)
        assert f"{form.pk}: " in session.setup["system"]
        assert tools.EXPERT_ANNOTATIONS not in [tool["name"] for tool in session.setup["tools"]]
        inputs = provider.requests[0].inputs
        assert (inputs["model"], inputs["effort"], inputs["max_tokens"]) == ("claude-opus-5-5", "max", tutor.MAX_TOKENS)
        assert inputs["system"] == session.setup["system"]

    def test_only_a_queued_session_is_written(self, enabled):
        session = uploaded(status=TutorSession.Status.READY)

        provider = write(session, [turn(present())])

        assert provider.requests == []
        assert session.status == TutorSession.Status.READY


class TestCorpusPages:
    @pytest.fixture
    def page(self):
        page = ItemImageFactory()
        ImageTextFactory(
            item_image=page,
            status=ImageText.Status.LIVE,
            content="<p>Dauid rex<lb/>omnibus prob<ex>is</ex> hominib<ex>us</ex></p>",
        )
        GraphFactory(item_image=page)
        return page

    def _fetched(self):
        picture = pictures.from_upload(jpeg(1000, 1400))
        return mock.patch.object(pictures, "from_page", return_value=picture)

    def test_the_page_is_fetched_and_introduced_with_its_charter_and_edition(self, enabled, page):
        session = TutorSession.objects.create(item_image=page)

        with self._fetched() as fetch:
            provider = write(session, [turn(present())])

        fetch.assert_called_once_with(page)
        assert (session.width, session.height) == (1000, 1400)
        assert session.picture.name == f"sessions/{session.pk}.jpg"
        intro = _messages(provider.requests[0])[0]["content"][1]["text"]
        historical = page.item_part.historical_item
        assert f"It is a page of the corpus: {page}." in intro
        assert f"The charter is {historical}, dated {historical.date}." in intro
        assert "Experts have annotated 1 glyphs on it" in intro
        assert "<edition>\nDauid rex\nomnibus prob(is) hominib(us)\n</edition>" in intro
        assert tools.EXPERT_ANNOTATIONS in [tool["name"] for tool in session.setup["tools"]]

    def test_a_draft_transcription_is_not_given_to_the_tutor(self, enabled):
        page = ItemImageFactory()
        ImageTextFactory(item_image=page, status=ImageText.Status.DRAFT, content="<p>secret draft</p>")
        session = TutorSession.objects.create(item_image=page)

        with self._fetched():
            provider = write(session, [turn(present())])

        intro = _messages(provider.requests[0])[0]["content"][1]["text"]
        assert "secret draft" not in intro
        assert "no published transcription" in intro

    def test_a_page_that_cannot_be_fetched_fails_in_words_for_the_student(self, enabled, page):
        session = TutorSession.objects.create(item_image=page)

        with mock.patch.object(pictures, "from_page", side_effect=images.ImageUnavailable("sipi down")):
            provider = write(session, [turn(present())])

        assert provider.requests == []
        assert session.status == TutorSession.Status.FAILED
        assert session.error == tutor.UNREADABLE

    def test_examples_a_tool_returned_are_shown_with_the_step(self, enabled, page):
        form = AllographFactory()
        example = GraphFactory(allograph=form, annotation=ring(100, 10, 140, 60))
        session = TutorSession.objects.create(item_image=page)
        steps = lesson()["steps"]
        steps[0] = {**steps[0], "allograph_id": form.pk, "example_glyph_ids": [example.pk]}
        fetch = call(tools.CORPUS_EXAMPLES, {"reason": "", "allograph_id": form.pk, "count": 2}, "toolu_examples")

        with (
            self._fetched(),
            mock.patch.object(tools, "_crop", return_value=jpeg(60, 60)),
            mock.patch.object(images, "dimensions", return_value=(800, 1000)),
            mock.patch.object(images, "identifier", return_value="https://iiif.example/p"),
        ):
            write(session, [turn(fetch), turn(present(lesson(steps=steps)))])

        assert session.seen_glyphs == [example.pk]
        step = session.walkthrough["steps"][0]
        assert step["example_glyph_ids"] == [example.pk]
        assert step["allograph_id"] == form.pk
        assert session.walkthrough["glyphs"][str(example.pk)]["crop_url"].startswith("https://iiif.example/p/")


class TestWhatTheStudentIsShown:
    def test_a_box_off_the_picture_is_handed_back_to_be_fixed(self, enabled):
        session = uploaded()
        steps = lesson()["steps"]
        wrong = [{**steps[0], "boxes": [{"x": 900, "y": 10, "width": 40, "height": 40, "label": "s"}]}]

        provider = write(session, [turn(present(lesson(steps=wrong), "toolu_1")), turn(present(call_id="toolu_2"))])

        (bounced,) = _last_results(provider.requests[1])
        assert bounced["is_error"] is True
        assert "Step 1: the box" in bounced["content"]
        assert "800 by 600 pixels" in bounced["content"]
        assert session.walkthrough["steps"][0]["boxes"] == [{**BOX, "label": "long s"}]

    def test_after_its_corrections_what_can_be_kept_of_a_lesson_is_kept(self, enabled):
        session = uploaded()
        steps = lesson()["steps"]
        wrong = [
            {
                **steps[0],
                "boxes": [{"x": 900, "y": 10, "width": 40, "height": 40, "label": "s"}, {**BOX, "label": "ok"}],
            }
        ]

        provider = write(session, [turn(present(lesson(steps=wrong)))])

        assert len(provider.requests) == tutor.MAX_CORRECTIONS + 1
        assert session.status == TutorSession.Status.READY
        assert session.walkthrough["steps"][0]["boxes"] == [{**BOX, "label": "ok"}]

    def test_a_glyph_no_tool_returned_is_never_shown(self, enabled):
        session = uploaded()
        steps = [{**lesson()["steps"][0], "example_glyph_ids": [424242]}]

        provider = write(session, [turn(present(lesson(steps=steps)))])

        assert "glyphs [424242] were not returned by a tool" in _last_results(provider.requests[1])[0]["content"]
        assert session.walkthrough["steps"][0]["example_glyph_ids"] == []
        assert session.walkthrough["glyphs"] == {}

    def test_a_letter_form_not_in_the_taxonomy_is_reported_and_dropped(self, enabled):
        session = uploaded()
        placeholder = AllographFactory(name="unmapped_allographs")
        steps = [{**lesson()["steps"][0], "allograph_id": placeholder.pk}]

        provider = write(session, [turn(present(lesson(steps=steps)))])

        assert f"there is no allograph {placeholder.pk}" in _last_results(provider.requests[1])[0]["content"]
        assert session.walkthrough["steps"][0]["allograph_id"] is None

    def test_a_lesson_is_capped_in_steps_boxes_and_length(self, enabled):
        step = {
            **lesson()["steps"][0],
            "title": "t" * 500,
            "boxes": [{**BOX, "label": "x"}] * 10,
        }
        settled, problems = tutor.settle_walkthrough(lesson(steps=[step] * 20), tools.Desk(b"", 800, 600))

        assert problems == []
        assert len(settled["steps"]) == tutor.MAX_STEPS
        assert len(settled["steps"][0]["boxes"]) == tutor.MAX_BOXES
        assert len(settled["steps"][0]["title"]) == 200

    def test_a_lesson_with_no_practice_has_none(self):
        settled, problems = tutor.settle_walkthrough(lesson(practice=None, steps=[]), tools.Desk(b"", 800, 600))

        assert problems == []
        assert settled["practice"] is None
        assert settled["steps"] == []

    @pytest.mark.parametrize(
        ("text", "cut"),
        [
            ("Das tironische \u201e7", True),
            ("\u201ea\u201c und \u201eb", True),
            ("Das Zeichen \u201e7\u201c steht f\u00fcr et.", False),
            ('Das Zeichen \u201e7" steht f\u00fcr et.', False),
            ("le signe \u00ab et", True),
            ("le signe \u00ab et \u00bb", False),
            ("The 'et' sign", False),
        ],
    )
    def test_a_text_that_stops_inside_a_quotation_is_found(self, text, cut):
        assert tutor._cut_short(text) is cut

    def test_a_lesson_cut_short_at_a_quotation_is_handed_back(self, enabled):
        session = uploaded()
        steps = [{**lesson()["steps"][0], "explanation": "Die tironische Note f\u00fcr \u201eet"}]

        provider = write(session, [turn(present(lesson(steps=steps), "toolu_1")), turn(present(call_id="toolu_2"))])

        (bounced,) = _last_results(provider.requests[1])
        assert bounced["is_error"] is True
        assert "steps[0].explanation: the text stops inside a quotation" in bounced["content"]
        assert session.walkthrough["steps"][0]["explanation"] == lesson()["steps"][0]["explanation"]

    def test_an_answer_cut_short_at_a_quotation_is_reported(self):
        raw = {"text": "Lesen Sie \u201eet", "boxes": [{**BOX, "label": "\u201ehier"}], "example_glyph_ids": []}

        _, problems = tutor.settle_reply(raw, tools.Desk(b"", 800, 600))

        assert [problem.split(":")[0] for problem in problems] == ["text", "boxes[0].label"]

    def test_the_tutor_is_told_to_quote_with_single_marks(self):
        assert "Quote with single quotation marks" in tutor.SYSTEM
        assert 'Never write the double quotation mark\n(")' in tutor.SYSTEM
        assert '"' not in tutor.SYSTEM.split("## Quoting")[0]


class TestHowALessonStops:
    def test_a_turn_without_a_call_is_asked_for_the_lesson(self, enabled):
        session = uploaded()

        provider = write(session, [turn(text="Here is what I see."), turn(present())])

        nudge = _messages(provider.requests[1])[-1]["content"]
        assert nudge == [
            {"type": "text", "text": "Call present_walkthrough now: the student sees nothing until you do."}
        ]
        assert session.status == TutorSession.Status.READY

    def test_a_turn_cut_off_by_the_token_limit_runs_none_of_its_calls(self, enabled):
        session = uploaded()

        provider = write(session, [turn(look(), stop_reason="max_tokens"), turn(present())])

        (result,) = _last_results(provider.requests[1])
        assert result["is_error"] is True
        assert "cut off" in result["content"]
        assert "Looking closer: to read line 1" not in [line["text"] for line in session.progress]

    def test_the_wrong_ending_is_refused(self, enabled):
        session = uploaded()
        early = call(tools.REPLY, {"text": "hi", "boxes": [], "example_glyph_ids": []}, "toolu_reply")

        provider = write(session, [turn(early), turn(present())])

        (result,) = _last_results(provider.requests[1])
        assert result["is_error"] is True
        assert result["content"] == "Not now: call present_walkthrough instead."

    def test_a_lesson_that_runs_out_of_turns_fails(self, enabled, monkeypatch):
        monkeypatch.setattr(tutor, "LESSON_TURNS", 3)
        session = uploaded()

        provider = write(session, [turn(look())])

        assert len(provider.requests) == 3
        assert session.status == TutorSession.Status.FAILED
        assert session.error == tutor.FAILED

    def test_a_refused_turn_leaves_the_session_refused(self, enabled):
        enabled.ML_INFERENCE_ENABLED = False
        session = uploaded()

        provider = write(session, [turn(present())])

        assert provider.requests == []
        assert session.status == TutorSession.Status.REFUSED
        assert session.error == tutor.UNAVAILABLE

    def test_a_failed_turn_fails_the_lesson_without_its_cause(self, enabled):
        session = uploaded()

        write(session, [ProviderError("Anthropic API returned 500 (api_error): secret details")])

        assert session.status == TutorSession.Status.FAILED
        assert session.error == tutor.FAILED

    def test_a_conversation_holds_no_more_pictures_than_its_limit(self, enabled, monkeypatch):
        monkeypatch.setattr(tutor, "MAX_PICTURES", 2)
        session = uploaded()

        provider = write(session, [turn(look("toolu_1")), turn(look("toolu_2")), turn(present())])

        (refused,) = _last_results(provider.requests[2])
        assert refused["is_error"] is True
        assert "as many pictures" in refused["content"]


class TestAnswering:
    def test_a_question_is_answered_in_the_same_conversation(self, ready):
        before = copy.deepcopy(ready.transcript)
        reply = call(
            tools.REPLY,
            {"text": "It is a round d.", "boxes": [{**BOX, "label": "d"}], "example_glyph_ids": []},
            "toolu_reply",
        )

        provider = answer(ready, [turn(reply)])

        assert ready.status == TutorSession.Status.READY
        student, tutor_message = ready.messages
        assert tutor_message["role"] == "tutor"
        assert tutor_message["text"] == "It is a round d."
        assert tutor_message["boxes"] == [{**BOX, "label": "d"}]
        sent = _messages(provider.requests[0])
        # The lesson's last turn is extended with the question, never changed.
        assert sent[:-1] == tutor.conversation(TutorSession(transcript=before[:-1]))
        assert sent[-1]["content"][:-1] == before[-1]["content"]
        assert sent[-1]["content"][-1] == {"type": "text", "text": "What is the third letter?"}

    def test_the_question_is_put_with_the_prompt_and_tools_the_lesson_had(self, ready):
        AllographFactory(name="added after the lesson")
        setup = dict(ready.setup)

        provider = answer(ready, [turn(text="A round d.")])

        assert provider.requests[0].inputs["system"] == setup["system"]
        assert provider.requests[0].inputs["tools"] == setup["tools"]

    def test_the_question_resends_the_lessons_last_request_as_it_was_written(self, enabled):
        # Compared as JSON text: the prompt cache matches the request byte for
        # byte, key order included, and dict equality would not see a change in it.
        session = uploaded()
        last = write(session, [turn(look()), turn(present())]).requests[-1].inputs
        session.messages = [{"role": "student", "text": "What is the third letter?", "at": "now"}]
        session.status = TutorSession.Status.WORKING
        session.save()

        sent = answer(session, [turn(text="A round d.")]).requests[0].inputs

        assert json.dumps(sent["tools"]) == json.dumps(last["tools"])
        assert json.dumps(sent["messages"][: len(last["messages"])]) == json.dumps(last["messages"])

    def test_an_answer_in_plain_text_is_taken_as_the_reply(self, ready):
        answer(ready, [turn(text="A round d.")])

        assert ready.messages[-1]["text"] == "A round d."
        assert ready.messages[-1]["boxes"] == []
        assert ready.status == TutorSession.Status.READY

    def test_a_failed_question_leaves_the_lesson_readable(self, ready):
        walkthrough = dict(ready.walkthrough)

        answer(ready, [ProviderError("boom")])

        assert ready.status == TutorSession.Status.READY
        assert ready.walkthrough == walkthrough
        assert ready.messages[-1]["failed"] is True
        assert ready.messages[-1]["text"] == tutor.FAILED

    def test_a_crash_answering_leaves_the_lesson_readable(self, ready):
        with mock.patch.object(tutor, "_desk", side_effect=RuntimeError("boom")), pytest.raises(RuntimeError):
            tutor.answer(ready.pk)

        ready.refresh_from_db()
        assert ready.status == TutorSession.Status.READY
        assert ready.messages[-1]["failed"] is True
        assert ready.messages[-1]["text"] == tutor.FAILED

    def test_a_crash_writing_a_lesson_ends_it_in_words_for_the_student(self, enabled):
        session = uploaded()

        with mock.patch.object(tutor, "_desk", side_effect=RuntimeError("boom")), pytest.raises(RuntimeError):
            tutor.write_lesson(session.pk)

        session.refresh_from_db()
        assert session.status == TutorSession.Status.FAILED
        assert session.error == tutor.FAILED

    def test_calls_left_open_by_a_failed_turn_are_answered_before_the_next_question(self, ready):
        ready.transcript.append({"role": "assistant", "content": turn(look("toolu_open"))["content"]})
        ready.save()

        provider = answer(ready, [turn(text="A round d.")])

        last = _messages(provider.requests[0])[-1]["content"]
        assert last[0] == {
            "type": "tool_result",
            "tool_use_id": "toolu_open",
            "content": "Interrupted before it ran.",
            "is_error": True,
        }
        assert last[-1] == {"type": "text", "text": "What is the third letter?"}

    def test_nothing_is_done_without_a_question_waiting(self, ready):
        ready.status = TutorSession.Status.READY
        ready.save()

        provider = answer(ready, [turn(text="unasked")])

        assert provider.requests == []

"""W1.4 — the baseline, and the measurement that decides whether to use it."""

import json
from unittest import mock

import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.ml.evaluation import character_error_rate
from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult
from apps.ml.services import ledger
from apps.ml.tests.factories import MLJobFactory
from apps.vision.services import htr


class _Answering:
    def __init__(self, text: str):
        self.text = text
        self.requests: list[InferenceRequest] = []

    def run(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        return InferenceResult(output={"text": self.text}, model_name="stub", cost_micros=13)


def _stub(text: str):
    provider = _Answering(text)
    registration = mock.Mock(hosted=True, factory=lambda: provider)
    registration.name = "openrouter"
    return provider, mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration)


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 10_000_000
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


@pytest.fixture
def reachable():
    with mock.patch("apps.vision.images.data_url", return_value="data:image/jpeg;base64,AAA"):
        yield


def _answer(*lines, notes=""):
    return json.dumps({"lines": list(lines), "notes": notes})


class TestCER:
    def test_an_exact_transcription_scores_zero(self):
        assert character_error_rate("Sciant presentes", "Sciant presentes") == 0.0

    def test_one_wrong_character_in_ten_scores_a_tenth(self):
        assert character_error_rate("abcdefghij", "abcdefghiX") == pytest.approx(0.1)

    def test_an_empty_prediction_scores_one(self):
        assert character_error_rate("Sciant", "") == 1.0

    def test_a_runaway_prediction_can_exceed_one(self):
        """Which is why a run reports a median, not only a mean."""
        assert character_error_rate("ab", "abcdefghij") > 1.0

    def test_an_empty_truth_is_not_a_division_by_zero(self):
        assert character_error_rate("", "") == 0.0
        assert character_error_rate("", "invented") == 1.0


class TestParse:
    def test_lines_are_kept_in_order_and_stripped(self):
        parsed = htr.parse(_answer("  Sciant presentes  ", "et futuri"))

        assert parsed["lines"] == ["Sciant presentes", "et futuri"]

    def test_an_answer_with_no_lines_is_unusable(self):
        with pytest.raises(ValueError, match="no lines"):
            htr.parse(_answer())

    def test_prose_is_unusable(self):
        with pytest.raises(ValueError, match="usable JSON"):
            htr.parse("The page is too damaged to read.")


class TestTEI:
    def test_lines_become_the_corpus_line_break_convention(self):
        tei = htr.to_tei({"lines": ["Sciant presentes", "et futuri"], "notes": ""}, model="stub")

        assert tei.count('<lb source="ms"/>') == 2

    def test_the_draft_names_its_model_and_says_it_is_machine_drafted(self):
        tei = htr.to_tei({"lines": ["Sciant"], "notes": ""}, model="anthropic/claude-opus-5")

        assert 'resp="#machine-draft"' in tei
        assert 'source="anthropic/claude-opus-5"' in tei

    def test_a_line_containing_markup_characters_is_escaped(self):
        tei = htr.to_tei({"lines": ["a < b & c"], "notes": ""}, model="stub")

        assert "&lt;" in tei and "&amp;" in tei


@pytest.mark.django_db
class TestSelection:
    def test_only_images_without_a_transcription_are_drafted(self):
        with_text = ItemImageFactory()
        ImageTextFactory(item_image=with_text, type=ImageText.Type.TRANSCRIPTION)
        without = ItemImageFactory()

        selected = htr.untranscribed()

        assert without in selected
        assert with_text not in selected

    def test_ground_truth_is_published_transcriptions_only(self):
        live = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant")
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.DRAFT, content="Sciant")
        ImageTextFactory(type=ImageText.Type.TRANSLATION, status=ImageText.Status.LIVE, content="Know")

        assert [text.pk for text in htr.transcribed()] == [live.pk]


@pytest.mark.django_db
class TestTranscribe:
    def test_a_draft_is_created_and_is_not_live(self, enabled, reachable):
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Sciant presentes"))

        with patch:
            tally = htr.transcribe(limit=1, selection=[image])

        assert tally["drafted"] == 1
        draft = ImageText.objects.get()
        assert draft.status == ImageText.Status.DRAFT
        assert 'resp="#machine-draft"' in draft.content

    def test_a_run_stops_when_machine_drafts_reach_the_limit(self, enabled, reachable, settings):
        settings.ML_REVIEW_LIMIT_DRAFTS = 2
        ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.DRAFT,
            content='<div resp="#machine-draft"></div>',
        )
        provider, patch = _stub(_answer("Sciant presentes"))

        with patch:
            tally = htr.transcribe(selection=[ItemImageFactory(), ItemImageFactory()])

        assert (tally["selected"], tally["drafted"], tally["queue_full"]) == (1, 1, 1)

    def test_a_person_s_draft_does_not_count_against_the_limit(self, enabled, reachable, settings):
        settings.ML_REVIEW_LIMIT_DRAFTS = 1
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.DRAFT, content="A scholar's draft")
        _, patch = _stub(_answer("Sciant presentes"))

        with patch:
            tally = htr.transcribe(selection=[ItemImageFactory()])

        assert (tally["drafted"], tally["queue_full"]) == (1, 0)

    def test_a_page_transcribed_mid_run_is_left_alone(self, enabled, reachable):
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Machine reading"))

        def _create_first(*args, **kwargs):
            ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION, content="A scholar's transcription")
            return InferenceResult(output={"text": _answer("Machine reading")}, model_name="stub")

        with patch, mock.patch.object(provider, "run", side_effect=_create_first):
            tally = htr.transcribe(limit=1, selection=[image])

        assert tally["drafted"] == 0
        assert ImageText.objects.count() == 1
        assert "scholar" in ImageText.objects.get().content

    def test_the_image_is_sent_and_the_ledger_records_the_call(self, enabled, reachable):
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Sciant"))

        with patch:
            htr.transcribe(limit=1, selection=[image])

        assert provider.requests[0].inputs["images"] == ["data:image/jpeg;base64,AAA"]
        assert MLJob.objects.get().task == "W1.4"

    def test_an_unfetchable_page_calls_no_model(self, enabled):
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Sciant"))

        with (
            patch,
            mock.patch("apps.vision.images.data_url", side_effect=htr.images.ImageUnavailable("gone")),
        ):
            tally = htr.transcribe(limit=1, selection=[image])

        assert tally["unavailable"] == 1
        assert MLJob.objects.count() == 0


class TestTruth:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("Rex Scott<ex>orum</ex> . Will<ex>elm</ex>o", "Rex Scott . Willo"),
            ('<supplied reason="lost">ea</supplied>ndem', "ndem"),
            ("Scott<EX>orum</EX>", "Scott"),
            ('<persName>Dauid</persName> T<seg type="witnesses">este</seg>', "Dauid Teste"),
            ('Sciant<lb source="ms">|</lb>presentes', "Sciant presentes"),
            ('con<lb source="ms">-|</lb>cessisse', "con cessisse"),
            ("<p>salutem</p><p>Sciant</p>", "salutem Sciant"),
            ("salutem &amp; benedictionem &lt;ex&gt;", "salutem & benedictionem <ex>"),
        ],
    )
    def test_the_truth_is_what_the_scribe_wrote(self, content, expected):
        assert htr.plain_text(content) == expected


@pytest.mark.django_db
class TestEvaluate:
    def test_a_perfect_reading_scores_zero_and_meets_the_target(self, enabled, reachable):
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            content="<p>Sciant presentes et futuri</p>",
        )
        provider, patch = _stub(_answer("Sciant presentes et futuri"))

        with patch:
            summary = htr.evaluate(limit=1, selection=[text])

        assert summary["scored"] == 1
        assert summary["median_cer"] == 0.0
        assert summary["target_met"] is True

    def test_markup_is_not_scored_against_the_model(self, enabled, reachable):
        """The model was asked for text, so it is measured on text."""
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            content='<div><lb source="ms"/>Sciant<lb source="ms"/>presentes</div>',
        )
        provider, patch = _stub(_answer("Sciant", "presentes"))

        with patch:
            summary = htr.evaluate(limit=1, selection=[text])

        assert summary["median_cer"] == 0.0

    def test_an_abbreviation_left_as_written_is_not_an_error(self, enabled, reachable):
        """The model is told to expand nothing, so the editor's expansions are not the truth."""
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            content='<p>W . Rex Scott<ex>orum</ex> <lb source="ms">|</lb> <supplied>Om</supplied>nibus</p>',
        )
        provider, patch = _stub(_answer("W . Rex Scott", "nibus"))

        with patch:
            summary = htr.evaluate(limit=1, selection=[text])

        assert summary["median_cer"] == 0.0

    def test_a_bad_reading_misses_the_target(self, enabled, reachable):
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant presentes et futuri"
        )
        provider, patch = _stub(_answer("Something else entirely here"))

        with patch:
            summary = htr.evaluate(limit=1, selection=[text])

        assert summary["target_met"] is False
        assert summary["median_cer"] > 0.10

    def test_the_median_of_an_even_count_lies_between_the_middle_two(self, enabled, reachable):
        reading = "Sciant presentes et futuri"
        right = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content=reading)
        wrong = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Omnibus")
        _, patch = _stub(_answer(reading))

        with patch:
            summary = htr.evaluate(limit=2, selection=[right, wrong])

        assert summary["median_cer"] == pytest.approx(summary["worst_cer"] / 2, abs=0.0001)

    def test_evaluating_writes_nothing(self, enabled, reachable):
        text = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant")
        provider, patch = _stub(_answer("Sciant"))

        with patch:
            htr.evaluate(limit=1, selection=[text])

        assert ImageText.objects.count() == 1

    def test_nothing_scored_reports_no_baseline_rather_than_a_zero(self, enabled, reachable):
        summary = htr.evaluate(selection=[])

        assert summary["median_cer"] is None
        assert summary["target_met"] is False


@pytest.mark.django_db
class TestHowAPageIsPut:
    def _evaluate(self, **reading):
        text = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant")
        provider, patch = _stub(_answer("Sciant"))
        with patch, mock.patch("apps.vision.images.data_url", return_value="data:image/jpeg;base64,AAA") as fetch:
            htr.evaluate(selection=[text], **reading)
        return fetch, provider.requests[0].inputs

    def test_by_default_the_page_is_1600_pixels_and_no_effort_is_asked(self, enabled):
        fetch, inputs = self._evaluate()

        assert fetch.call_args.kwargs == {"size": 1600}
        assert inputs["max_tokens"] == htr.MAX_TOKENS
        assert "effort" not in inputs

    def test_a_larger_page_more_effort_and_a_longer_answer_can_be_asked_for(self, enabled):
        fetch, inputs = self._evaluate(size=2576, effort="max", max_tokens=64000)

        assert fetch.call_args.kwargs == {"size": 2576}
        assert inputs["effort"] == "max"
        assert inputs["max_tokens"] == 64000

    def test_drafting_puts_the_page_the_same_way(self, enabled):
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Sciant"))

        with patch, mock.patch("apps.vision.images.data_url", return_value="data:image/jpeg;base64,AAA") as fetch:
            htr.transcribe(selection=[image], size=2576, effort="high", max_tokens=32000)

        assert fetch.call_args.kwargs == {"size": 2576}
        assert (provider.requests[0].inputs["effort"], provider.requests[0].inputs["max_tokens"]) == ("high", 32000)


class TestTheCommand:
    def _call(self, *args):
        from django.core.management import call_command

        empty = {"selected": 0, "scored": 0, "median_cer": None, "target_met": False, "per_image": []}
        with (
            mock.patch.object(htr, "evaluate", return_value=empty) as evaluate,
            mock.patch.object(htr, "transcribe", return_value={"drafted": 0, "queue_full": 0}) as transcribe,
        ):
            call_command("htr_baseline", *args, stdout=mock.MagicMock())
        return evaluate, transcribe

    def test_the_reading_options_reach_the_measurement(self):
        evaluate, _ = self._call("--size", "2576", "--effort", "max", "--max-tokens", "64000")

        assert {key: evaluate.call_args.kwargs[key] for key in ("size", "effort", "max_tokens")} == {
            "size": 2576,
            "effort": "max",
            "max_tokens": 64000,
        }

    def test_and_the_drafting(self):
        _, transcribe = self._call("--draft", "--size", "2576", "--effort", "high")

        assert transcribe.call_args.kwargs["size"] == 2576
        assert transcribe.call_args.kwargs["effort"] == "high"
        assert transcribe.call_args.kwargs["max_tokens"] == htr.MAX_TOKENS

    def test_without_them_the_defaults_are_kept(self):
        evaluate, _ = self._call()

        assert {key: evaluate.call_args.kwargs[key] for key in ("size", "effort", "max_tokens")} == {
            "size": 1600,
            "effort": None,
            "max_tokens": htr.MAX_TOKENS,
        }


@pytest.mark.django_db
class TestReadingPagesAtOnce:
    """The model calls are stood in for, so no worker thread touches the test database."""

    def _texts(self, count):
        return [
            ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content=f"Sciant {n}")
            for n in range(count)
        ]

    def _reading(self, text):
        return mock.Mock(model_name="stub"), {"lines": [text], "notes": ""}, "ok"

    def test_several_pages_are_read_at_the_same_time(self):
        import threading

        texts = self._texts(2)
        together = threading.Barrier(2, timeout=5)

        def ask(image, **_):
            together.wait()  # Raises unless both pages are being read at once.
            return self._reading(next(t.content for t in texts if t.item_image_id == image.pk))

        with mock.patch.object(htr, "_ask", side_effect=lambda service, image, **kw: ask(image)):
            summary = htr.evaluate(selection=texts, workers=2)

        assert summary["scored"] == 2
        assert summary["median_cer"] == 0.0

    def test_the_scores_keep_the_selections_order_however_the_pages_finish(self):
        import threading

        texts = self._texts(3)
        first_may_finish = threading.Event()

        def ask(image):
            content = next(t.content for t in texts if t.item_image_id == image.pk)
            if image.pk == texts[0].item_image_id:
                assert first_may_finish.wait(timeout=5)
            elif image.pk == texts[2].item_image_id:
                first_may_finish.set()
            return self._reading(content)

        with mock.patch.object(htr, "_ask", side_effect=lambda service, image, **kw: ask(image)):
            summary = htr.evaluate(selection=texts, workers=3)

        assert [row["image_text_id"] for row in summary["per_image"]] == [text.pk for text in texts]

    def test_a_refusal_cancels_the_pages_still_waiting(self):
        import threading

        texts = self._texts(5)
        refused = threading.Event()
        asked = []

        def ask(image):
            asked.append(image.pk)
            if image.pk == texts[0].item_image_id:
                refused.set()
                return None, None, "refused"
            assert refused.wait(timeout=5)
            return self._reading(next(t.content for t in texts if t.item_image_id == image.pk))

        with mock.patch.object(htr, "_ask", side_effect=lambda service, image, **kw: ask(image)):
            summary = htr.evaluate(selection=texts, workers=2)

        # The refused page and the one read beside it; the other three never started.
        assert sorted(asked) == sorted([texts[0].item_image_id, texts[1].item_image_id])
        assert (summary["refused"], summary["scored"], summary["selected"]) == (1, 1, 5)

    def test_one_at_a_time_a_refusal_stops_the_run(self):
        texts = self._texts(3)

        with mock.patch.object(htr, "_ask", return_value=(None, None, "refused")) as ask:
            summary = htr.evaluate(selection=texts)

        assert ask.call_count == 1
        assert summary["refused"] == 1

    def test_each_worker_closes_its_database_connection(self):
        texts = self._texts(3)

        with (
            mock.patch.object(htr, "_ask", side_effect=lambda service, image, **kw: self._reading("Sciant 0")),
            mock.patch.object(htr.connections, "close_all") as close_all,
        ):
            htr.evaluate(selection=texts, workers=2)

        assert close_all.call_count == 3

    def test_one_at_a_time_reads_on_this_thread_and_leaves_its_connection_open(self):
        texts = self._texts(2)

        with (
            mock.patch.object(htr, "_ask", side_effect=lambda service, image, **kw: self._reading("Sciant 0")),
            mock.patch.object(htr.connections, "close_all") as close_all,
        ):
            htr.evaluate(selection=texts)

        close_all.assert_not_called()

    def test_drafting_reads_pages_at_once_too(self, enabled):
        import threading

        pages = [ItemImageFactory(), ItemImageFactory()]
        together = threading.Barrier(2, timeout=5)
        job = MLJobFactory(model_name="stub")

        def ask(image):
            together.wait()
            return job, {"lines": ["Sciant"], "notes": ""}, "ok"

        with mock.patch.object(htr, "_ask", side_effect=lambda service, image, **kw: ask(image)):
            tally = htr.transcribe(selection=pages, workers=2)

        assert tally["drafted"] == 2
        drafts = ImageText.objects.filter(status=ImageText.Status.DRAFT)
        assert drafts.count() == 2
        # A batch's draft is found from the ledger like a requested one.
        for draft in drafts:
            assert list(ledger.jobs_touching("imagetext", draft.pk)) == [job]

    def test_the_command_passes_the_workers_on(self):
        from django.core.management import call_command

        empty = {"selected": 0, "scored": 0, "median_cer": None, "target_met": False, "per_image": []}
        with mock.patch.object(htr, "evaluate", return_value=empty) as evaluate:
            call_command("htr_baseline", "--workers", "6", stdout=mock.MagicMock())

        assert evaluate.call_args.kwargs["workers"] == 6


def _edition(lines, *, ex=True, suspension=True, tironian=False):
    """A transcription in the corpus's encoding, of `lines` written lines."""
    words = []
    for n in range(lines):
        word = f"Will<ex>elm</ex>o{n}" if ex else f"Willelmo{n}"
        if suspension:
            word += " andr’"
        if tironian:
            word += " ⁊ laicis"
        words.append(word)
    return "<p>" + "".join(f'<lb source="ms">|</lb>{word}' for word in words) + "</p>"


class TestTheEditionsText:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("Rex Scott<ex>orum</ex> . Will<ex>elm</ex>o", "Rex Scottorum . Willelmo"),
            ('<supplied reason="lost">ea</supplied>ndem', "ndem"),
            ('<persName>Dauid</persName> T<seg type="witnesses">est<ex>ibus</ex></seg>', "Dauid Testibus"),
            ('Sciant<lb source="ms">|</lb>presentes', "Sciant presentes"),
            ("salutem &amp; benedictionem", "salutem & benedictionem"),
        ],
    )
    def test_an_edited_reading_is_scored_against_the_expansions_too(self, content, expected):
        assert htr.edition_text(content) == expected

    def test_its_lines_keep_the_expansions_and_drop_the_rest_of_the_markup(self):
        content = (
            '<p><seg type="address">Alex<ex>ander</ex> dei</seg><lb source="ms">|</lb>'
            '<persName>Will<ex>elm</ex>o</persName> <supplied>Om</supplied>nibus<lb source="ms">|</lb> </p>'
        )

        assert htr.edition_lines(content) == ["Alex<ex>ander</ex> dei", "Will<ex>elm</ex>o nibus"]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Omnibus Probis Hominibus", "omnibus probis hominibus"),
            ("clericis ⁊ laicis", "clericis et laicis"),
            ("salutem . Sciatis", "salutem sciatis"),
            ("apud Coldingham’ . deo", "apud coldingham deo"),
            ("Testibus  Ricardo", "testibus ricardo"),
        ],
    )
    def test_the_normalised_reading_drops_what_editors_do_differently(self, text, expected):
        assert htr.normalised(text) == expected

    def test_a_models_marked_expansions_are_scored_by_their_letters(self):
        assert htr.reading_text(["Scott<ex>orum</ex>  Will<ex>elm</ex>o", "salutem"]) == "Scottorum Willelmo salutem"


@pytest.mark.django_db
class TestTheExamples:
    def _text(self, content):
        return ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content=content)

    def test_the_first_three_in_the_corpus_majority_convention_are_chosen(self):
        short = self._text(_edition(htr.EXEMPLAR_LINES - 1))
        unmarked = self._text(_edition(12, ex=False))
        unsuspended = self._text(_edition(12, suspension=False))
        tironian = self._text(_edition(12, tironian=True))
        first, second, third, fourth = (self._text(_edition(12)) for _ in range(4))

        chosen = htr.exemplars()

        assert chosen == [first, second, third]
        assert not {short, unmarked, unsuspended, tironian, fourth} & set(chosen)

    def test_the_edited_instructions_show_their_opening_lines(self):
        shown = [self._text(_edition(12)), self._text(_edition(11))]

        system = htr.system_for(htr.EDITED, shown)

        assert system.count("<example>") == 2
        assert "Will<ex>elm</ex>o9 andr’" in system
        assert "Will<ex>elm</ex>o10" not in system  # Ten lines of each, no more.
        assert "{examples}" not in system
        assert "Expand abbreviations" in system

    def test_the_diplomatic_instructions_are_unchanged(self):
        assert htr.system_for(htr.DIPLOMATIC) == htr.SYSTEM

    def test_an_unknown_style_is_refused(self):
        with pytest.raises(ValueError, match="No HTR style"):
            htr.system_for("normalised")


@pytest.mark.django_db
class TestAnEditedReading:
    def test_is_scored_against_the_editors_text_and_never_on_an_example(self, enabled, reachable):
        shown = [
            ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content=_edition(12))
            for _ in range(htr.EXEMPLARS)
        ]
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            content='<p>W . Rex Scott<ex>orum</ex> <lb source="ms">|</lb> <supplied>Om</supplied>nibus</p>',
        )
        provider, patch = _stub(_answer("W . Rex Scott<ex>orum</ex>", "nibus"))

        with patch:
            summary = htr.evaluate(selection=[*shown, text], style=htr.EDITED)

        assert summary["selected"] == 1
        assert summary["exemplars"] == sorted(example.pk for example in shown)
        assert summary["median_cer"] == 0.0
        assert summary["style"] == htr.EDITED
        assert len(provider.requests) == 1
        assert provider.requests[0].inputs["system"].count("<example>") == htr.EXEMPLARS

    def test_a_diplomatic_reading_of_the_same_page_is_scored_without_the_expansions(self, enabled, reachable):
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="<p>Rex Scott<ex>orum</ex></p>"
        )
        provider, patch = _stub(_answer("Rex Scott"))

        with patch:
            summary = htr.evaluate(selection=[text])

        assert summary["median_cer"] == 0.0
        assert (summary["style"], summary["exemplars"]) == (htr.DIPLOMATIC, [])
        assert provider.requests[0].inputs["system"] == htr.SYSTEM

    def test_a_diplomatic_reading_is_shown_no_examples_and_holds_none_out(self, enabled, reachable):
        texts = [
            ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content=_edition(12))
            for _ in range(htr.EXEMPLARS)
        ]
        provider, patch = _stub(_answer("Willelmo"))

        with patch:
            summary = htr.evaluate(selection=texts)

        assert (summary["selected"], summary["scored"], summary["exemplars"]) == (htr.EXEMPLARS, htr.EXEMPLARS, [])

    def test_a_difference_of_convention_is_scored_apart_from_a_misreading(self, enabled, reachable):
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION,
            status=ImageText.Status.LIVE,
            content="<p>Omnibus probis hominibus clericis et laicis salutem .</p>",
        )
        provider, patch = _stub(_answer("omnibus probis hominibus clericis ⁊ laicis salutem"))

        with patch:
            summary = htr.evaluate(selection=[text])

        assert summary["median_cer"] > 0.0
        assert summary["median_cer_normalised"] == 0.0
        assert summary["mean_cer_normalised"] == 0.0
        assert summary["per_image"][0]["cer_normalised"] == 0.0

    def test_drafting_asks_for_the_editions_text_and_keeps_its_expansions(self, enabled, reachable):
        for _ in range(htr.EXEMPLARS):
            ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content=_edition(12))
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Rex Scott<ex>orum</ex> <b>"))

        with patch:
            htr.transcribe(selection=[image], style=htr.EDITED)

        assert provider.requests[0].inputs["system"].count("<example>") == htr.EXEMPLARS
        draft = ImageText.objects.get(item_image=image)
        assert "Rex Scott<ex>orum</ex> &lt;b&gt;" in draft.content


class TestTheDraftsExpansions:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("Scott<ex>orum</ex> et Will<ex>elm</ex>o", "Scott<ex>orum</ex> et Will<ex>elm</ex>o"),
            ("Scott<ex>orum", "Scott&lt;ex&gt;orum"),
            ("Scott<ex><b>orum</b></ex>", "Scott&lt;ex&gt;&lt;b&gt;orum&lt;/b&gt;&lt;/ex&gt;"),
            ("a < b & c", "a &lt; b &amp; c"),
        ],
    )
    def test_only_a_whole_expansion_becomes_markup(self, line, expected):
        tei = htr.to_tei({"lines": [line]}, model="stub")

        assert f'<lb source="ms"/>{expected}</div>' in tei

    def test_the_command_passes_the_style_on(self):
        from django.core.management import call_command

        empty = {"selected": 0, "scored": 0, "median_cer": None, "target_met": False, "per_image": []}
        with mock.patch.object(htr, "evaluate", return_value=empty) as evaluate:
            call_command("htr_baseline", "--style", "edited", stdout=mock.MagicMock())

        assert evaluate.call_args.kwargs["style"] == htr.EDITED

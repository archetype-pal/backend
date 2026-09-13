"""W1.4 — the baseline, and the measurement that decides whether to use it."""

import json
from unittest import mock

import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.ml.evaluation import character_error_rate
from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult
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
    settings.ML_DAILY_COST_CAP_MICROS = 0
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

    def test_a_page_transcribed_mid_run_is_left_alone(self, enabled, reachable):
        image = ItemImageFactory()
        provider, patch = _stub(_answer("Machine reading"))

        def _create_first(*args, **kwargs):
            ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION, content="A scholar's transcription")
            return InferenceResult(output={"text": _answer("Machine reading")}, model_name="stub")

        with patch:
            with mock.patch.object(provider, "run", side_effect=_create_first):
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

    def test_a_bad_reading_misses_the_target(self, enabled, reachable):
        text = ImageTextFactory(
            type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant presentes et futuri"
        )
        provider, patch = _stub(_answer("Something else entirely here"))

        with patch:
            summary = htr.evaluate(limit=1, selection=[text])

        assert summary["target_met"] is False
        assert summary["median_cer"] > 0.10

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

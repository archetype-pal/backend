"""The agent loop: its bounds, its logging, and what it does with a tool result.

Every test here drives a stub provider. The point is never what a model says —
it is that the loop around the model terminates, records, and refuses.
"""

import json
from unittest import mock

import pytest

from apps.agents import services
from apps.agents.models import AgentRun, ServiceIdentity
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory
from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult
from apps.users.tests.factories import UserFactory

PUBLIC = ["search_charters", "get_charter", "get_image_regions", "cite_record"]


class _Scripted:
    """Returns a prepared sequence of turns, then repeats the last one."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests: list[InferenceRequest] = []

    def run(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        turn = self.turns[min(len(self.requests) - 1, len(self.turns) - 1)]
        return InferenceResult(output=turn, model_name="stub", cost_micros=7)


def _call(name, arguments, call_id="call-1"):
    return {"id": call_id, "name": name, "arguments": json.dumps(arguments)}


def _stub(turns):
    provider = _Scripted(turns)
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
def identity(db):
    return ServiceIdentity.objects.create(
        slug=services.DEFAULT_IDENTITY, allowed_tools=PUBLIC, enabled=True, max_turns=4
    )


@pytest.fixture
def published(db):
    return ImageTextFactory(
        type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant presentes David rex"
    )


@pytest.mark.django_db
class TestGuards:
    def test_a_disabled_identity_answers_nothing(self, enabled, identity):
        identity.enabled = False
        identity.save()

        with pytest.raises(services.AgentError, match="disabled"):
            services.ask("Who witnessed this?")

    def test_a_missing_identity_is_named(self, enabled):
        with pytest.raises(services.AgentError, match="ask-archetype"):
            services.ask("Who witnessed this?")

    def test_an_identity_with_no_usable_tools_refuses(self, enabled, identity):
        identity.allowed_tools = ["compare_hands"]
        identity.save()

        with pytest.raises(services.AgentError, match="no usable tools"):
            services.ask("Do these share a hand?")

    def test_an_over_long_question_is_refused_before_any_call(self, enabled, identity):
        with pytest.raises(services.AgentError, match="limited to"):
            services.ask("x" * 3000)

        assert MLJob.objects.count() == 0

    def test_the_quota_is_per_requester_not_per_identity(self, enabled, identity):
        identity.daily_run_quota = 1
        identity.save()
        provider, patch = _stub([{"text": "An answer.", "tool_calls": []}])

        with patch:
            services.ask("First?", requester_key="alice")
            with pytest.raises(services.AgentError, match="quota"):
                services.ask("Second?", requester_key="alice")
            # A different requester still has their own allowance — a shared
            # global quota would let one caller spend everyone else's.
            services.ask("Mine?", requester_key="bob")

        # Two rows, not three: a question refused by the quota is never run, so
        # it leaves no run behind. That is deliberate — a log entry per rejected
        # attempt would be an unbounded write anyone could drive.
        assert AgentRun.objects.count() == 2

    def test_a_signed_in_user_is_bucketed_by_account(self, enabled, identity):
        identity.daily_run_quota = 1
        identity.save()
        user = UserFactory()
        provider, patch = _stub([{"text": "An answer.", "tool_calls": []}])

        with patch:
            services.ask("First?", actor=user)
            with pytest.raises(services.AgentError, match="quota"):
                services.ask("Second?", actor=user)


@pytest.mark.django_db
class TestLoop:
    def test_a_direct_answer_is_recorded(self, enabled, identity):
        provider, patch = _stub([{"text": "The corpus cannot answer this yet.", "tool_calls": []}])

        with patch:
            run = services.ask("Which charters mention Perth?")

        assert run.status == AgentRun.Status.ANSWERED
        assert run.answer == "The corpus cannot answer this yet."
        assert run.turns == 1
        assert run.cost_micros == 7

    def test_a_tool_call_is_executed_and_its_result_returned_to_the_model(self, enabled, identity, published):
        provider, patch = _stub(
            [
                {"text": "", "tool_calls": [_call("search_charters", {"query": "David rex"})]},
                {"text": "One charter names David rex.", "tool_calls": []},
            ]
        )

        with patch:
            run = services.ask("Which charters name David rex?")

        assert run.status == AgentRun.Status.ANSWERED
        assert run.turns == 2
        assert run.tool_calls[0]["name"] == "search_charters"
        # The second request replays the assistant turn and the tool result.
        replayed = provider.requests[1].inputs["messages"]
        assert replayed[-2]["role"] == "assistant"
        assert replayed[-1]["role"] == "tool"
        assert str(published.pk) in replayed[-1]["content"]

    def test_a_verified_citation_is_kept_on_the_run(self, enabled, identity, published):
        provider, patch = _stub(
            [
                {
                    "text": "",
                    "tool_calls": [
                        _call("cite_record", {"claim": "David rex granted it.", "image_text_id": published.pk})
                    ],
                },
                {"text": "David rex granted it.", "tool_calls": []},
            ]
        )

        with patch:
            run = services.ask("Who granted it?")

        assert run.citations[0]["image_text_id"] == published.pk
        assert run.citations[0]["claim"] == "David rex granted it."

    def test_an_unresolvable_citation_never_reaches_the_answer(self, enabled, identity):
        provider, patch = _stub(
            [
                {"text": "", "tool_calls": [_call("cite_record", {"claim": "x", "image_text_id": 999999})]},
                {"text": "I could not verify that.", "tool_calls": []},
            ]
        )

        with patch:
            run = services.ask("Who granted it?")

        assert run.citations == []
        # The model is told why, so it can correct itself rather than repeat it.
        assert "no such published charter" in provider.requests[1].inputs["messages"][-1]["content"]

    def test_a_tool_the_identity_lacks_is_refused_mid_loop(self, enabled, identity, published):
        provider, patch = _stub(
            [
                {"text": "", "tool_calls": [_call("fetch_witnesses", {})]},
                {"text": "That is not available.", "tool_calls": []},
            ]
        )

        with patch:
            run = services.ask("Who witnessed it?")

        assert run.status == AgentRun.Status.ANSWERED
        assert "not permitted" in provider.requests[1].inputs["messages"][-1]["content"]

    def test_malformed_tool_arguments_do_not_kill_the_run(self, enabled, identity):
        provider, patch = _stub(
            [
                {"text": "", "tool_calls": [{"id": "c", "name": "search_charters", "arguments": "{not json"}]},
                {"text": "Recovered.", "tool_calls": []},
            ]
        )

        with patch:
            run = services.ask("Anything?")

        assert run.status == AgentRun.Status.ANSWERED
        assert "not valid JSON" in provider.requests[1].inputs["messages"][-1]["content"]

    def test_a_model_that_never_stops_is_cut_off(self, enabled, identity, published):
        provider, patch = _stub([{"text": "", "tool_calls": [_call("search_charters", {"query": "Sciant"})]}])

        with patch:
            run = services.ask("Loop forever?")

        assert run.status == AgentRun.Status.EXHAUSTED
        assert run.turns == identity.max_turns
        assert len(provider.requests) == identity.max_turns


@pytest.mark.django_db
class TestPolicyGates:
    def test_the_spend_cap_stops_the_agent_and_is_recorded(self, enabled, identity, settings):
        settings.ML_INFERENCE_ENABLED = False
        provider, patch = _stub([{"text": "hi", "tool_calls": []}])

        with patch:
            run = services.ask("Anything?")

        assert run.status == AgentRun.Status.REFUSED
        assert len(provider.requests) == 0
        assert AgentRun.objects.get().error

    def test_the_hosted_data_gate_stops_the_agent(self, enabled, identity, settings):
        settings.ML_HOSTED_PROVIDERS_ENABLED = False
        provider, patch = _stub([{"text": "hi", "tool_calls": []}])

        with patch:
            run = services.ask("Anything?")

        assert run.status == AgentRun.Status.REFUSED
        assert len(provider.requests) == 0

    def test_every_turn_is_one_ledger_row(self, enabled, identity, published):
        provider, patch = _stub(
            [
                {"text": "", "tool_calls": [_call("search_charters", {"query": "Sciant"})]},
                {"text": "Done.", "tool_calls": []},
            ]
        )

        with patch:
            services.ask("Which charters?")

        assert MLJob.objects.filter(task="W3.1", status=MLJob.Status.SUCCEEDED).count() == 2

    def test_the_ledger_stores_no_corpus_text(self, enabled, identity, published):
        provider, patch = _stub([{"text": "Done.", "tool_calls": []}])

        with patch:
            services.ask("Sciant presentes?")

        job = MLJob.objects.get()
        assert "Sciant" not in json.dumps(job.params)
        assert "Sciant" not in (job.error or "")
        # A digest of the inputs, and no copy of them.
        assert job.input_ref

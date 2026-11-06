"""The public endpoints and the operator's log."""

import json
from unittest import mock

import pytest

from apps.agents import services
from apps.agents.models import AgentRun, ServiceIdentity
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory
from apps.ml.providers import InferenceRequest, InferenceResult, ProviderError

PUBLIC = ["search_charters", "get_charter", "get_image_regions", "cite_record"]


class _Answering:
    def __init__(self, output):
        self.output = output

    def run(self, request: InferenceRequest) -> InferenceResult:
        return InferenceResult(output=self.output, model_name="stub", cost_micros=3)


def _stub(output):
    registration = mock.Mock(hosted=True, factory=lambda: _Answering(output))
    registration.name = "openrouter"
    return mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration)


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
        slug=services.DEFAULT_IDENTITY, allowed_tools=PUBLIC, enabled=True, max_turns=3
    )


@pytest.mark.django_db
class TestAsk:
    def test_a_visitor_never_sees_the_ledger_s_error(self, api_client, enabled, identity):
        provider = mock.Mock()
        provider.run.side_effect = ProviderError("OpenRouter rejected the key: sk-or-123")
        registration = mock.Mock(hosted=True, factory=lambda: provider)
        registration.name = "openrouter"

        with mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration):
            response = api_client.post("/api/v1/agent/ask/", {"question": "Who?"}, format="json")

        assert response.data["status"] == "failed"
        assert "sk-or-123" not in str(response.data)
        assert "sk-or-123" in AgentRun.objects.get().error

    def test_anyone_can_ask_and_gets_an_answer(self, api_client, enabled, identity):
        with _stub({"text": "The corpus cannot answer this yet.", "tool_calls": []}):
            response = api_client.post("/api/v1/agent/ask/", {"question": "Who witnessed it?"}, format="json")

        assert response.status_code == 200
        assert response.data["status"] == "answered"
        assert response.data["citations"] == []

    def test_an_empty_question_is_a_bad_request(self, api_client, enabled, identity):
        response = api_client.post("/api/v1/agent/ask/", {"question": ""}, format="json")

        assert response.status_code == 400

    def test_a_disabled_agent_is_unavailable_not_a_bad_request(self, api_client, enabled, identity):
        identity.enabled = False
        identity.save()

        response = api_client.post("/api/v1/agent/ask/", {"question": "Anything?"}, format="json")

        assert response.status_code == 503

    def test_an_answer_does_not_leak_what_it_cost_or_who_asked(self, api_client, enabled, identity):
        with _stub({"text": "Done.", "tool_calls": []}):
            response = api_client.post("/api/v1/agent/ask/", {"question": "Anything?"}, format="json")

        assert "cost_micros" not in response.data
        assert "requester_key" not in response.data

    def test_the_run_is_logged_with_a_requester_bucket_that_is_not_an_address(self, api_client, enabled, identity):
        with _stub({"text": "Done.", "tool_calls": []}):
            api_client.post("/api/v1/agent/ask/", {"question": "Anything?"}, format="json")

        run = AgentRun.objects.get()
        assert run.question == "Anything?"
        assert run.requester_key and "127.0.0.1" not in run.requester_key

    def test_a_citation_survives_to_the_response(self, api_client, enabled, identity):
        text = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, status=ImageText.Status.LIVE, content="Sciant")
        turn = {
            "text": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "name": "cite_record",
                    "arguments": json.dumps({"claim": "It exists.", "image_text_id": text.pk}),
                }
            ],
        }
        # The stub answers the same way every turn, so the loop exhausts — which
        # is exactly the case where a citation must still be reported.
        with _stub(turn):
            response = api_client.post("/api/v1/agent/ask/", {"question": "Anything?"}, format="json")

        assert response.data["status"] == "exhausted"
        assert response.data["citations"][0]["claim"] == "It exists."


@pytest.mark.django_db
class TestThrottle:
    def test_a_burst_is_cut_off_before_it_reaches_a_model(self, api_client, enabled, identity, settings):
        settings.DRF_THROTTLE_AGENT_RATE = "2/hour"

        with _stub({"text": "Done.", "tool_calls": []}):
            first = api_client.post("/api/v1/agent/ask/", {"question": "One?"}, format="json")
            second = api_client.post("/api/v1/agent/ask/", {"question": "Two?"}, format="json")
            third = api_client.post("/api/v1/agent/ask/", {"question": "Three?"}, format="json")

        assert [first.status_code, second.status_code, third.status_code] == [200, 200, 429]
        # The throttled request never became a run, so it never became a model
        # call — which is the point of putting the bucket in front of the loop.
        assert AgentRun.objects.count() == 2


@pytest.fixture
def behind_proxy(settings):
    """The deployment: one proxy in front, so the visitor is the last forwarded address."""
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    return settings


def _ask_from(api_client, visitor: str, question: str = "Anything?"):
    # Every request reaches Django from the proxy's address; only the header differs.
    return api_client.post(
        "/api/v1/agent/ask/",
        {"question": question},
        format="json",
        REMOTE_ADDR="172.18.0.5",
        HTTP_X_FORWARDED_FOR=visitor,
    )


@pytest.mark.django_db
class TestQuotaBehindProxy:
    def test_two_visitors_behind_the_proxy_are_two_requesters(self, api_client, enabled, identity, behind_proxy):
        with _stub({"text": "Done.", "tool_calls": []}):
            _ask_from(api_client, "203.0.113.7")
            _ask_from(api_client, "198.51.100.23")
            _ask_from(api_client, "203.0.113.7")

        keys = list(AgentRun.objects.order_by("pk").values_list("requester_key", flat=True))
        assert keys[0] == keys[2]
        assert keys[0] != keys[1]

    def test_one_visitor_spending_the_quota_leaves_the_next_one_theirs(
        self, api_client, enabled, identity, behind_proxy
    ):
        identity.daily_run_quota = 1
        identity.save()

        with _stub({"text": "Done.", "tool_calls": []}):
            first = _ask_from(api_client, "203.0.113.7", "One?")
            again = _ask_from(api_client, "203.0.113.7", "Two?")
            other = _ask_from(api_client, "198.51.100.23", "Mine?")

        assert [first.status_code, again.status_code, other.status_code] == [200, 503, 200]
        assert "quota" in again.data["detail"]

    def test_a_forged_forwarded_address_does_not_buy_a_fresh_quota(self, api_client, enabled, identity, behind_proxy):
        identity.daily_run_quota = 1
        identity.save()

        with _stub({"text": "Done.", "tool_calls": []}):
            _ask_from(api_client, "203.0.113.7", "One?")
            # nginx appends the address it saw; the visitor controls only what comes before it.
            forged = _ask_from(api_client, "10.9.9.9, 203.0.113.7", "Two?")

        assert forged.status_code == 503


@pytest.mark.django_db
class TestToolsEndpoint:
    def test_the_limits_are_public(self, api_client, identity):
        response = api_client.get("/api/v1/agent/tools/")

        assert response.status_code == 200
        by_name = {tool["name"]: tool for tool in response.data["tools"]}
        assert by_name["compare_hands"]["available"] is False
        assert "W1.2/W1.3" in by_name["compare_hands"]["unavailable_reason"]
        assert by_name["search_charters"]["granted"] is True

    def test_it_answers_before_any_identity_exists(self, api_client, db):
        response = api_client.get("/api/v1/agent/tools/")

        assert response.status_code == 200
        assert response.data["enabled"] is False


@pytest.mark.django_db
class TestManagement:
    def test_the_run_log_is_superuser_only(self, api_client, authenticated_client, identity):
        assert api_client.get("/api/v1/management/agent-runs/").status_code in (401, 403)
        assert authenticated_client.get("/api/v1/management/agent-runs/").status_code == 403

    def test_a_superuser_sees_the_question_and_the_tool_calls(self, management_client, enabled, identity):
        with _stub({"text": "Done.", "tool_calls": []}):
            services.ask("Who witnessed it?", requester_key="alice")

        response = management_client.get("/api/v1/management/agent-runs/")

        assert response.data["results"][0]["question"] == "Who witnessed it?"
        assert response.data["results"][0]["cost_micros"] == 3

    def test_the_log_cannot_be_edited(self, management_client, enabled, identity):
        with _stub({"text": "Done.", "tool_calls": []}):
            services.ask("Who witnessed it?")
        run = AgentRun.objects.get()

        response = management_client.patch(
            f"/api/v1/management/agent-runs/{run.pk}/", {"question": "rewritten"}, format="json"
        )

        assert response.status_code == 405

    def test_identities_are_superuser_only_and_editable(self, management_client, authenticated_client):
        assert authenticated_client.get("/api/v1/management/agent-identities/").status_code == 403

        response = management_client.post(
            "/api/v1/management/agent-identities/",
            {"slug": "curator", "allowed_tools": ["search_charters"], "enabled": False},
            format="json",
        )

        assert response.status_code == 201
        assert ServiceIdentity.objects.get(slug="curator").enabled is False

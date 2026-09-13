"""The OpenRouter provider — the programme's default hosted route.

Mocked throughout: a live call would spend money on every CI run. What is worth
pinning is that a router's two hazards are handled — the recipient is not fixed
at configuration time, and the cost must come from the response rather than a
price table that goes stale.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, resolve_provider
from apps.ml.providers.openrouter import OpenRouterProvider
from apps.ml.services import InferenceService


def _response(*, text="Sanctio identified.", finish="stop", cost=0.0123, provider="Anthropic"):
    return SimpleNamespace(
        id="gen-abc",
        provider=provider,
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=200, cost=cost, model_extra={}),
    )


def _sdk(response=None, error=None):
    class _Err(Exception):
        status_code = 500

    module = SimpleNamespace(
        AuthenticationError=type("AuthenticationError", (_Err,), {}),
        NotFoundError=type("NotFoundError", (_Err,), {}),
        RateLimitError=type("RateLimitError", (_Err,), {}),
        APIStatusError=type("APIStatusError", (_Err,), {}),
        APIConnectionError=type("APIConnectionError", (_Err,), {}),
    )
    create = mock.Mock(side_effect=error) if error else mock.Mock(return_value=response)
    module.OpenAI = mock.Mock(
        return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )
    module._create = create
    return module


@pytest.fixture
def keyed(settings):
    settings.ML_OPENROUTER_API_KEY = "sk-or-test"
    settings.ML_OPENROUTER_MODEL = "anthropic/claude-opus-5"
    settings.ML_OPENROUTER_ALLOW_DATA_COLLECTION = False
    settings.ML_OPENROUTER_ALLOWED_PROVIDERS = []
    return settings


def _run(module, inputs=None):
    with mock.patch.dict("sys.modules", {"openai": module}):
        return OpenRouterProvider().run(InferenceRequest(task="W2.1", inputs=inputs or {"prompt": "Find the sanctio."}))


class TestRouting:
    def test_data_collection_is_denied_by_default(self, keyed):
        """The corpus includes five archives' photography; routing to a provider
        that logs prompts for training is not a default worth having."""
        module = _sdk(_response())

        _run(module)

        assert module._create.call_args.kwargs["extra_body"]["provider"]["data_collection"] == "deny"

    def test_data_collection_can_be_allowed_explicitly(self, keyed):
        keyed.ML_OPENROUTER_ALLOW_DATA_COLLECTION = True
        module = _sdk(_response())

        _run(module)

        assert module._create.call_args.kwargs["extra_body"]["provider"]["data_collection"] == "allow"

    def test_upstreams_can_be_pinned(self, keyed):
        """A known recipient is worth more than an automatic retry on an unknown one."""
        keyed.ML_OPENROUTER_ALLOWED_PROVIDERS = ["anthropic", "google"]
        module = _sdk(_response())

        _run(module)

        assert module._create.call_args.kwargs["extra_body"]["provider"]["only"] == ["anthropic", "google"]

    def test_no_pin_means_no_only_key(self, keyed):
        module = _sdk(_response())

        _run(module)

        assert "only" not in module._create.call_args.kwargs["extra_body"]["provider"]


class TestReporting:
    def test_cost_comes_from_the_response_not_a_price_table(self, keyed):
        module = _sdk(_response(cost=0.0123))

        result = _run(module)

        assert result.cost_micros == 12_300

    def test_a_missing_cost_reports_zero_rather_than_guessing(self, keyed):
        module = _sdk(_response(cost=None))

        assert _run(module).cost_micros == 0

    def test_the_upstream_that_served_it_is_recorded(self, keyed):
        """For a router, 'which model produced this' means which upstream ran."""
        module = _sdk(_response(provider="Anthropic"))

        assert _run(module).model_version == "Anthropic"

    def test_tokens_and_text_are_reported(self, keyed):
        module = _sdk(_response())

        result = _run(module)

        assert (result.input_tokens, result.output_tokens) == (1000, 200)
        assert result.output["text"] == "Sanctio identified."

    def test_the_prompt_is_hashed_not_returned(self, keyed):
        module = _sdk(_response())

        result = _run(module, {"prompt": "corpus text", "system": "You are a diplomatist."})

        assert len(result.prompt_hash) == 64
        assert "corpus text" not in result.prompt_hash

    def test_the_model_is_a_per_call_choice(self, keyed):
        module = _sdk(_response())

        _run(module, {"prompt": "x", "model": "z-ai/glm-5.3-flash"})

        assert module._create.call_args.kwargs["model"] == "z-ai/glm-5.3-flash"


class TestFailures:
    def test_a_missing_key_is_refused_before_any_call(self, settings):
        settings.ML_OPENROUTER_API_KEY = ""
        module = _sdk(_response())

        with pytest.raises(ProviderError, match="not set"):
            _run(module)

        module._create.assert_not_called()

    def test_a_missing_prompt_is_refused_before_any_call(self, keyed):
        module = _sdk(_response())

        with pytest.raises(ProviderError, match="needs a 'prompt'"):
            _run(module, {"system": "only a system prompt"})

        module._create.assert_not_called()

    def test_a_content_filter_is_an_error_not_an_empty_answer(self, keyed):
        module = _sdk(_response(text="", finish="content_filter"))

        with pytest.raises(ProviderError, match="declined"):
            _run(module)

    def test_an_empty_choices_list_is_an_error(self, keyed):
        response = _response()
        response.choices = []
        module = _sdk(response)

        with pytest.raises(ProviderError, match="no choices"):
            _run(module)

    @pytest.mark.parametrize(
        "kind", ["AuthenticationError", "NotFoundError", "RateLimitError", "APIStatusError", "APIConnectionError"]
    )
    def test_sdk_errors_become_provider_errors(self, keyed, kind):
        module = _sdk()
        module._create.side_effect = getattr(module, kind)("boom")

        with pytest.raises(ProviderError):
            _run(module)


@pytest.mark.django_db
class TestItStaysOffByDefault:
    def test_registered_as_hosted(self):
        assert resolve_provider("openrouter").hosted is True

    def test_refused_while_the_data_policy_gate_is_shut(self, settings):
        settings.ML_INFERENCE_ENABLED = True
        settings.ML_HOSTED_PROVIDERS_ENABLED = False

        job = InferenceService().submit(task="W2.1", provider="openrouter", inputs={"prompt": "hello"})

        assert job.status == MLJob.Status.REFUSED
        assert "hosted" in job.error

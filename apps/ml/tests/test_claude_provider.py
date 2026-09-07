"""The hosted Claude provider — the first that calls a real model.

Every test here mocks the SDK. A test that made a live call would spend money on
every CI run and fail without a key, and neither is a property worth pinning.
What is worth pinning is that the provider reports honestly to the ledger, and
that it stays refused until someone turns it on.
"""

from types import SimpleNamespace
from unittest import mock

import pytest

from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, ProviderError, resolve_provider
from apps.ml.providers.claude import ClaudeProvider, estimate_cost_micros
from apps.ml.services import InferenceService


def _response(*, text="Sanctio clause identified.", stop_reason="end_turn", **usage):
    return SimpleNamespace(
        id="msg_01ABC",
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=usage.get("input_tokens", 1000),
            output_tokens=usage.get("output_tokens", 200),
            cache_read_input_tokens=usage.get("cache_read", 0),
            cache_creation_input_tokens=0,
        ),
    )


def _sdk(response=None, error=None):
    """A stand-in for the `anthropic` module, with the error classes it raises."""

    class _Err(Exception):
        status_code = 500
        type = "api_error"

    module = SimpleNamespace(
        NotFoundError=type("NotFoundError", (_Err,), {}),
        RateLimitError=type("RateLimitError", (_Err,), {}),
        APIStatusError=type("APIStatusError", (_Err,), {}),
        APIConnectionError=type("APIConnectionError", (_Err,), {}),
    )
    create = mock.Mock(side_effect=error) if error else mock.Mock(return_value=response)
    module.Anthropic = mock.Mock(
        return_value=SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    )
    module._create = create
    return module


class TestPricing:
    def test_cost_is_integer_micros(self):
        # 1000 in + 200 out on Opus 5 at $5/$25 per MTok.
        assert estimate_cost_micros("claude-opus-5", 1000, 200) == 1000 * 5 + 200 * 25

    def test_an_unpriced_model_reports_zero_rather_than_guessing(self):
        assert estimate_cost_micros("some-future-model", 1000, 200) == 0


class TestTheCall:
    def _run(self, module, inputs=None):
        with mock.patch.dict("sys.modules", {"anthropic": module}):
            return ClaudeProvider().run(InferenceRequest(task="W2.1", inputs=inputs or {"prompt": "Find the sanctio."}))

    def test_reports_model_tokens_and_cost_to_the_ledger(self):
        module = _sdk(_response())

        result = self._run(module)

        assert result.model_name == "claude-opus-5"
        assert result.model_version == "msg_01ABC"
        assert result.input_tokens == 1000
        assert result.output_tokens == 200
        assert result.cost_micros == 1000 * 5 + 200 * 25
        assert result.cost_currency == "USD"
        assert result.output["text"] == "Sanctio clause identified."

    def test_cached_reads_are_counted_toward_spend(self):
        """Over-reporting is the safe direction for a cap to err in."""
        module = _sdk(_response(cache_read=500))

        result = self._run(module)

        assert result.input_tokens == 1500

    def test_the_prompt_is_hashed_not_returned(self):
        module = _sdk(_response())

        result = self._run(module, {"prompt": "corpus text here", "system": "You are a diplomatist."})

        assert len(result.prompt_hash) == 64
        assert "corpus text" not in result.prompt_hash

    def test_a_refusal_is_an_error_not_an_empty_answer(self):
        """A refusal returns HTTP 200; reading .content would yield nothing."""
        module = _sdk(_response(text="", stop_reason="refusal"))

        with pytest.raises(ProviderError, match="declined"):
            self._run(module)

    def test_a_missing_prompt_is_refused_before_any_call(self):
        module = _sdk(_response())

        with pytest.raises(ProviderError, match="needs a 'prompt'"):
            self._run(module, {"system": "only a system prompt"})

        module._create.assert_not_called()

    def test_adaptive_thinking_and_fallbacks_are_requested(self):
        module = _sdk(_response())

        self._run(module)

        payload = module._create.call_args.kwargs
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["fallbacks"] == "default"

    @pytest.mark.parametrize("kind", ["NotFoundError", "RateLimitError", "APIStatusError", "APIConnectionError"])
    def test_sdk_errors_become_provider_errors(self, kind):
        """The ledger records a failure; it never sees an SDK exception type."""
        module = _sdk()
        module._create.side_effect = getattr(module, kind)("boom")

        with pytest.raises(ProviderError):
            self._run(module)


@pytest.mark.django_db
class TestItStaysOffByDefault:
    def test_the_provider_is_registered_as_hosted(self):
        assert resolve_provider("claude").hosted is True

    def test_it_is_refused_while_the_data_policy_gate_is_shut(self, settings):
        settings.ML_INFERENCE_ENABLED = True
        settings.ML_HOSTED_PROVIDERS_ENABLED = False

        job = InferenceService().submit(task="W2.1", provider="claude", inputs={"prompt": "hello"})

        assert job.status == MLJob.Status.REFUSED
        assert "hosted" in job.error

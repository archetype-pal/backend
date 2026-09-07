"""A hosted-language-model provider, backed by the Anthropic API.

The first provider in this programme that actually calls a model. It is
registered `hosted=True`, so it stays refused until both switches are on: the
data policy gate (`ML_HOSTED_PROVIDERS_ENABLED`) and the kill switch
(`ML_INFERENCE_ENABLED`). Sending corpus material off our infrastructure is a
decision the platform makes explicitly, once, rather than implicitly at every
call site.

What it reports back is as important as what it returns. `InferenceResult`
carries the model, the resolved version, the prompt hash, the token counts and
the cost in integer micros, because the ledger's whole purpose is to answer
*which model produced this record, and what did it cost* — and only the provider
knows its own pricing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

from django.conf import settings

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens, as integer micros to avoid float money."""

    input_micros_per_token: int
    output_micros_per_token: int


# $/1M tokens -> micros per token. Recorded here rather than fetched so a cost
# in the ledger is reproducible from the code that wrote it; revisit when
# Anthropic's pricing changes, and note that a stale entry under-reports rather
# than fails, so it is worth checking against an invoice.
PRICING: dict[str, Price] = {
    "claude-opus-5": Price(5, 25),
    "claude-sonnet-5": Price(2, 10),
    "claude-haiku-4-5": Price(1, 5),
}


def estimate_cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    """Cost in millionths of a dollar. Unknown models cost 0 and say so."""
    price = PRICING.get(model)
    if price is None:
        logger.warning("No price recorded for %s; the ledger will under-report this call.", model)
        return 0
    return input_tokens * price.input_micros_per_token + output_tokens * price.output_micros_per_token


class ClaudeProvider:
    """Calls the Anthropic Messages API and reports the call to the ledger.

    Inputs it understands:
      `prompt`  — required, the user turn.
      `system`  — optional system prompt.
      `model`, `max_tokens`, `effort` — optional overrides.
    """

    def run(self, request: InferenceRequest) -> InferenceResult:
        import anthropic

        inputs: Mapping[str, Any] = request.inputs
        prompt = inputs.get("prompt")
        if not prompt:
            raise ProviderError("A Claude inference needs a 'prompt' in its inputs.")

        model = str(inputs.get("model") or getattr(settings, "ML_CLAUDE_MODEL", DEFAULT_MODEL))
        max_tokens = int(inputs.get("max_tokens") or DEFAULT_MAX_TOKENS)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": str(prompt)}],
            # Adaptive thinking: the model decides how much reasoning a given
            # charter needs, rather than us guessing a fixed budget per task.
            "thinking": {"type": "adaptive"},
            # A policy decline is answered by re-running on a fallback model
            # inside the same call, so one refused charter does not abort a
            # corpus-scale pass.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        if inputs.get("system"):
            payload["system"] = str(inputs["system"])
        if inputs.get("effort"):
            payload["output_config"] = {"effort": str(inputs["effort"])}

        client = anthropic.Anthropic()
        try:
            response = client.beta.messages.create(**payload)
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"No such model '{model}': {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(f"Rate limited: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API returned {exc.status_code} ({exc.type}): {exc}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"Could not reach the Anthropic API: {exc}") from exc

        # Check before reading content: a refusal returns 200 with no answer.
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise ProviderError(f"The model declined this request (category: {category}).")

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = response.usage
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        # Cached reads are billed at a fraction, but counting them at full rate
        # over-reports rather than under-reports, which is the safe direction for
        # a spend cap to err in.
        input_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        input_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

        return InferenceResult(
            output={"text": text, "stop_reason": response.stop_reason},
            model_name=model,
            # The response's own id pins the exact serving version for the
            # ledger, which a model alias alone does not.
            model_version=str(getattr(response, "id", "") or ""),
            prompt_hash=content_digest({"system": inputs.get("system", ""), "prompt": prompt}),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=estimate_cost_micros(model, input_tokens, output_tokens),
            cost_currency="USD",
        )

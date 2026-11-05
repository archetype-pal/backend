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
from decimal import Decimal
import logging
from typing import Any

from django.conf import settings

from .base import InferenceRequest, InferenceResult, ProviderError, client_limits
from .null import content_digest

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MAX_TOKENS = 16000


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens, held as integer micro-dollars so no price is a float.

    Per million tokens, not per token: Haiku 5.5's $0.10 is a tenth of a
    micro-dollar a token, which a per-token integer cannot hold.
    """

    input_micros_per_mtok: int
    output_micros_per_mtok: int


def usd_per_mtok(input_usd: str, output_usd: str) -> Price:
    """A price as Anthropic lists it, in dollars per million input and output tokens."""
    return Price(int(Decimal(input_usd) * 1_000_000), int(Decimal(output_usd) * 1_000_000))


# Anthropic's list prices, recorded here rather than fetched so a cost in the
# ledger is reproducible from the code that wrote it; revisit when they change,
# and note that a stale entry under-reports rather than fails, so it is worth
# checking against an invoice. A refusal fallback can answer with an older
# model, so those stay listed. Haiku 5.5 costs more past a 100K-token prompt,
# which no call here sends.
PRICING: dict[str, Price] = {
    "claude-fable-5-1": usd_per_mtok("10", "50"),
    "claude-fable-5": usd_per_mtok("10", "50"),
    "claude-opus-5-5": usd_per_mtok("4", "20"),
    "claude-opus-5": usd_per_mtok("5", "25"),
    "claude-opus-4-8": usd_per_mtok("5", "25"),
    "claude-sonnet-5-5": usd_per_mtok("2", "10"),
    "claude-sonnet-5": usd_per_mtok("2", "10"),
    "claude-haiku-5-5": usd_per_mtok("0.10", "0.50"),
    "claude-haiku-4-5": usd_per_mtok("1", "5"),
}


def estimate_cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    """Cost in millionths of a dollar, rounded up. Unknown models cost 0 and say so.

    Up, because a fraction of a micro-dollar left off every call adds up to an
    under-reported total, and a spend cap should err the other way.
    """
    price = PRICING.get(model)
    if price is None:
        logger.warning("No price recorded for %s; the ledger will under-report this call.", model)
        return 0
    per_million = input_tokens * price.input_micros_per_mtok + output_tokens * price.output_micros_per_mtok
    return -(-per_million // 1_000_000)


def image_block(url: str) -> dict[str, Any]:
    """One image as a Messages API content block: a `data:` URL inline, any other URL by reference."""
    if url.startswith("data:"):
        header, _, data = url.partition(",")
        media_type = header[len("data:") :].split(";")[0]
        if ";base64" not in header or not media_type.startswith("image/") or not data:
            raise ProviderError("An image data URL must be base64 and of an image type.")
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
    if url.startswith(("https://", "http://")):
        return {"type": "image", "source": {"type": "url", "url": url}}
    raise ProviderError("An image must be a data: URL or an http(s) URL.")


class ClaudeProvider:
    """Calls the Anthropic Messages API and reports the call to the ledger.

    Inputs it understands:
      `prompt`  — required, the user turn.
      `system`  — optional system prompt.
      `images`  — optional list of `data:` or http(s) URLs, placed before the
                  prompt, which is where the model reads them best.
      `model`, `max_tokens`, `effort` — optional overrides.

    The call is streamed. A page image read with adaptive thinking can take
    minutes, longer than an unstreamed request may stay open, and the SDK
    refuses an unstreamed one whose `max_tokens` implies that.
    """

    def run(self, request: InferenceRequest) -> InferenceResult:
        import anthropic

        inputs: Mapping[str, Any] = request.inputs
        prompt = inputs.get("prompt")
        if not prompt:
            raise ProviderError("A Claude inference needs a 'prompt' in its inputs.")

        model = str(inputs.get("model") or getattr(settings, "ML_CLAUDE_MODEL", DEFAULT_MODEL))
        max_tokens = int(inputs.get("max_tokens") or DEFAULT_MAX_TOKENS)

        images = [str(url) for url in inputs.get("images") or []]
        content: str | list[dict[str, Any]] = str(prompt)
        if images:
            content = [image_block(url) for url in images] + [{"type": "text", "text": str(prompt)}]

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
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

        client = anthropic.Anthropic(**client_limits(request))
        try:
            with client.beta.messages.stream(**payload) as stream:
                response = stream.get_final_message()
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

        # The model that answered: a refusal fallback can hand the call to
        # another, and the ledger names the one that wrote the answer.
        served = str(getattr(response, "model", "") or model)
        hashed: dict[str, Any] = {"system": inputs.get("system", ""), "prompt": prompt}
        if images:
            hashed["images"] = images
        return InferenceResult(
            output={"text": text, "stop_reason": response.stop_reason},
            model_name=served,
            # The response's own id pins the exact serving version for the
            # ledger, which a model alias alone does not.
            model_version=str(getattr(response, "id", "") or ""),
            prompt_hash=content_digest(hashed),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=estimate_cost_micros(served, input_tokens, output_tokens),
            cost_currency="USD",
        )

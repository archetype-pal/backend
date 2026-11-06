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
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"


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


# What a cached token costs, as a fraction of an uncached input token: a read
# a tenth, a write to the five-minute cache a quarter more, and to the hour's
# cache double. Held as twentieths so that every price stays an integer.
CACHE_READ_TWENTIETHS = 2
CACHE_WRITE_5M_TWENTIETHS = 25
CACHE_WRITE_1H_TWENTIETHS = 40


def estimate_cost_micros(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_reads: int = 0,
    cache_writes_5m: int = 0,
    cache_writes_1h: int = 0,
) -> int:
    """Cost in millionths of a dollar, rounded up. Unknown models cost the dearest listed, and say so.

    `input_tokens` are the uncached ones; tokens read from or written to the
    prompt cache are priced at their own rates. Rounded up, because a fraction
    of a micro-dollar left off every call adds up to an under-reported total,
    and a spend cap should err the other way.
    """
    price = PRICING.get(model)
    if price is None:
        # Not 0: a model priced at nothing never reaches a spend cap.
        logger.warning("No price recorded for %s; charging the ledger the dearest listed.", model)
        price = max(PRICING.values(), key=lambda listed: listed.input_micros_per_mtok)
    per_twenty_million = (
        20 * input_tokens * price.input_micros_per_mtok
        + CACHE_READ_TWENTIETHS * cache_reads * price.input_micros_per_mtok
        + CACHE_WRITE_5M_TWENTIETHS * cache_writes_5m * price.input_micros_per_mtok
        + CACHE_WRITE_1H_TWENTIETHS * cache_writes_1h * price.input_micros_per_mtok
        + 20 * output_tokens * price.output_micros_per_mtok
    )
    return -(-per_twenty_million // 20_000_000)


def _cache_writes(usage: Any) -> tuple[int, int]:
    """Tokens written to the five-minute and the hour's cache.

    The usage breaks writes down by how long they are kept when it can; a
    write it does not break down is priced as the five-minute cache's.
    """
    total = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    split = getattr(usage, "cache_creation", None)
    hour = int(getattr(split, "ephemeral_1h_input_tokens", 0) or 0) if split is not None else 0
    return max(total - hour, 0), hour


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


def _block(block: Any) -> dict[str, Any]:
    """A response content block as plain data, to be sent back unchanged in a later turn."""
    if hasattr(block, "model_dump"):
        return dict(block.model_dump(mode="json", exclude_none=True))
    return {key: value for key, value in vars(block).items() if value is not None}


def _dropped_thinking(response: Any) -> list[dict[str, Any]]:
    """Replayed thinking the API dropped rather than refuse the turn, each one logged."""
    dropped = [_block(change) for change in getattr(response, "input_transformations", None) or []]
    for change in dropped:
        logger.warning("The API dropped replayed thinking at %s (%s).", change.get("path"), change.get("reason"))
    return dropped


def _declined(response: Any, model: str, category: str) -> ProviderError:
    """A refusal, carrying what it cost: a model that declines has been billed."""
    uncached = int(getattr(response.usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)
    return ProviderError(
        f"The model declined this request (category: {category}).",
        input_tokens=uncached,
        output_tokens=output_tokens,
        cost_micros=estimate_cost_micros(str(getattr(response, "model", "") or model), uncached, output_tokens),
    )


class ClaudeProvider:
    """Calls the Anthropic Messages API and reports the call to the ledger.

    Inputs it understands:
      `prompt`   — the user turn. Required unless `messages` is given.
      `messages` — a whole conversation in the Messages API's shape, for a
                   caller running a tool loop: it replays the assistant turns
                   it was given, thinking blocks included, unchanged. Given
                   instead of `prompt` and `images`, not as well.
      `system`   — optional system prompt.
      `images`   — optional list of `data:` or http(s) URLs, placed before the
                   prompt, which is where the model reads them best.
      `tools`    — optional tool definitions in the Messages API's shape.
      `model`, `max_tokens`, `effort` — optional overrides.

    The output carries the answer's text, its content blocks as they came (for
    a caller to replay), its tool calls as `{"id", "name", "input"}`, and any
    replayed thinking the API dropped (`input_transformations`).

    The call is streamed. A page image read with adaptive thinking can take
    minutes, longer than an unstreamed request may stay open, and the SDK
    refuses an unstreamed one whose `max_tokens` implies that.
    """

    def run(self, request: InferenceRequest) -> InferenceResult:
        import anthropic

        inputs: Mapping[str, Any] = request.inputs
        prompt = inputs.get("prompt")
        conversation = inputs.get("messages")
        if not prompt and not conversation:
            raise ProviderError("A Claude inference needs a 'prompt' or 'messages' in its inputs.")

        model = str(inputs.get("model") or getattr(settings, "ML_CLAUDE_MODEL", DEFAULT_MODEL))
        max_tokens = int(inputs.get("max_tokens") or DEFAULT_MAX_TOKENS)

        images = [str(url) for url in inputs.get("images") or []]
        messages: list[dict[str, Any]]
        if conversation:
            messages = [dict(message) for message in conversation]
        else:
            content: str | list[dict[str, Any]] = str(prompt)
            if images:
                content = [image_block(url) for url in images] + [{"type": "text", "text": str(prompt)}]
            messages = [{"role": "user", "content": content}]

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
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
        if inputs.get("tools"):
            payload["tools"] = [dict(tool) for tool in inputs["tools"]]
        if conversation:
            # A conversation resends every turn before the new one, so the
            # cache holds it from one turn to the next.
            payload["cache_control"] = {"type": "ephemeral"}
            # It also replays the thinking of its earlier turns, which the API
            # checks against the conversation that produced it. Should the
            # replay differ by a byte, the API refuses the turn unless told to
            # drop that thinking instead: an answer without the reasoning
            # beats none. Each drop comes back in `input_transformations`.
            payload["thinking"] = {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"}}
            payload["betas"] = [*payload["betas"], THINKING_BINDING_BETA]

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
            raise _declined(response, model, category)

        text = "".join(block.text for block in response.content if block.type == "text")
        tool_calls = [
            {"id": block.id, "name": block.name, "input": dict(block.input or {})}
            for block in response.content
            if block.type == "tool_use"
        ]
        dropped = _dropped_thinking(response)
        usage = response.usage
        uncached = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        cache_reads = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        writes_5m, writes_1h = _cache_writes(usage)
        # The ledger counts every token of the prompt, cached or not; the cost
        # prices each at its own rate.
        input_tokens = uncached + cache_reads + writes_5m + writes_1h

        # The model that answered: a refusal fallback can hand the call to
        # another, and the ledger names the one that wrote the answer.
        served = str(getattr(response, "model", "") or model)
        hashed: dict[str, Any] = {"system": inputs.get("system", ""), "prompt": prompt}
        if images:
            hashed["images"] = images
        if conversation:
            hashed = {"system": inputs.get("system", ""), "messages": messages, "tools": payload.get("tools", [])}
        return InferenceResult(
            output={
                "text": text,
                "stop_reason": response.stop_reason,
                "content": [_block(block) for block in response.content],
                "tool_calls": tool_calls,
                "input_transformations": dropped,
            },
            model_name=served,
            # The response's own id pins the exact serving version for the
            # ledger, which a model alias alone does not.
            model_version=str(getattr(response, "id", "") or ""),
            prompt_hash=content_digest(hashed),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_micros=estimate_cost_micros(
                served,
                uncached,
                output_tokens,
                cache_reads=cache_reads,
                cache_writes_5m=writes_5m,
                cache_writes_1h=writes_1h,
            ),
            cost_currency="USD",
        )

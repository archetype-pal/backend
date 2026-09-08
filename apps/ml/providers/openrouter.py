"""OpenRouter — one key and one bill across many models.

The programme's default hosted provider. Different items want different models —
a cheap fast one for bulk classification, a strong one for translation drafts,
a long-context one for whole-corpus questions — and routing them through one
endpoint means that choice is a per-call argument rather than a new integration
each time.

Two things about a *router* that a direct provider does not have, and that this
project has to care about:

**The recipient is not fixed at configuration time.** OpenRouter chooses an
upstream provider per request. So `data_collection: "deny"` is set by default
here — it restricts routing to providers OpenRouter believes do not log prompts
for training. Their own documentation calls that "not a definitive source of
third party data policies, but represents our best knowledge", and this corpus
includes five archives' photography, so it is a control rather than a guarantee.
`ML_OPENROUTER_ALLOWED_PROVIDERS` pins the upstreams outright when that is not
good enough.

**Cost comes back from the response.** OpenRouter reports what the call actually
cost, so the ledger stops depending on a hardcoded price table that goes stale
the moment a vendor changes rates — which is what the direct Claude provider has
to do.

The SDK is the OpenAI client because OpenRouter speaks that protocol; it is not
talking to OpenAI.
"""

from collections.abc import Mapping
import logging
from typing import Any

from django.conf import settings

from .base import InferenceRequest, InferenceResult, ProviderError
from .null import content_digest

logger = logging.getLogger(__name__)

BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-opus-5"
DEFAULT_MAX_TOKENS = 16000

# OpenRouter denominates cost in credits. Recorded into the ledger's integer
# micros; confirm the credit-to-currency rate against an invoice before quoting
# a ledger total as money.
MICROS_PER_CREDIT = 1_000_000


def _cost_micros(usage: Any) -> int:
    """Cost the provider reported, in integer micros. 0 when it reported none."""
    cost = getattr(usage, "cost", None)
    if cost is None:
        extra = getattr(usage, "model_extra", None) or {}
        cost = extra.get("cost")
    if cost is None:
        logger.warning("OpenRouter returned no cost; this call will under-report in the ledger.")
        return 0
    return int(round(float(cost) * MICROS_PER_CREDIT))


class OpenRouterProvider:
    """Calls OpenRouter's chat-completions endpoint and reports the call.

    Inputs it understands:
      `prompt`   — the user turn. Required unless `messages` is given.
      `system`   — optional system prompt, prepended to `prompt`.
      `messages` — a full conversation, for a caller running a multi-turn loop
                   that must replay prior turns verbatim. Given instead of
                   `prompt`/`system`, not as well.
      `tools`, `tool_choice` — optional, OpenAI tool-calling shape.
      `model`, `max_tokens`, `temperature` — optional overrides.
    """

    def run(self, request: InferenceRequest) -> InferenceResult:
        import openai

        inputs: Mapping[str, Any] = request.inputs
        prompt = inputs.get("prompt")
        conversation = inputs.get("messages")
        if not prompt and not conversation:
            raise ProviderError("An OpenRouter inference needs a 'prompt' or 'messages' in its inputs.")

        api_key = getattr(settings, "ML_OPENROUTER_API_KEY", "")
        if not api_key:
            raise ProviderError("ML_OPENROUTER_API_KEY is not set.")

        model = str(inputs.get("model") or getattr(settings, "ML_OPENROUTER_MODEL", DEFAULT_MODEL))

        messages: list[dict[str, Any]]
        if conversation:
            messages = [dict(message) for message in conversation]
        else:
            messages = []
            if inputs.get("system"):
                messages.append({"role": "system", "content": str(inputs["system"])})
            messages.append({"role": "user", "content": str(prompt)})

        routing: dict[str, Any] = {
            "data_collection": ("allow" if getattr(settings, "ML_OPENROUTER_ALLOW_DATA_COLLECTION", False) else "deny")
        }
        allowed = list(getattr(settings, "ML_OPENROUTER_ALLOWED_PROVIDERS", []) or [])
        if allowed:
            # `only` narrows routing to named upstreams. It also removes most
            # fallbacks, which is the point: a known recipient is worth more here
            # than an automatic retry on an unknown one.
            routing["only"] = allowed

        client = openai.OpenAI(
            base_url=BASE_URL,
            api_key=api_key,
            default_headers={
                "HTTP-Referer": getattr(settings, "SITE_URL", "") or "https://archetype.elghareeb.space",
                "X-Title": "Archetype",
            },
        )

        optional: dict[str, Any] = {}
        if inputs.get("tools"):
            optional["tools"] = list(inputs["tools"])
            optional["tool_choice"] = inputs.get("tool_choice") or "auto"

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=int(inputs.get("max_tokens") or DEFAULT_MAX_TOKENS),
                temperature=inputs.get("temperature"),
                extra_body={"provider": routing},
                **optional,
            )
        except openai.AuthenticationError as exc:
            raise ProviderError(f"OpenRouter rejected the key: {exc}") from exc
        except openai.NotFoundError as exc:
            raise ProviderError(f"No such model '{model}' on OpenRouter: {exc}") from exc
        except openai.RateLimitError as exc:
            raise ProviderError(f"Rate limited: {exc}") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenRouter returned {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(f"Could not reach OpenRouter: {exc}") from exc

        choices = response.choices or []
        if not choices:
            raise ProviderError("OpenRouter returned no choices.")
        choice = choices[0]
        text = (choice.message.content or "") if choice.message else ""
        finish = choice.finish_reason or ""
        if finish == "content_filter":
            raise ProviderError("The upstream model declined this request (content filter).")

        # Normalised out of the SDK objects here so nothing downstream has to
        # import a model client just to read an answer.
        tool_calls = [
            {"id": call.id, "name": call.function.name, "arguments": call.function.arguments or "{}"}
            for call in (getattr(choice.message, "tool_calls", None) or [])
            if getattr(call, "function", None)
        ]

        usage = response.usage
        return InferenceResult(
            output={"text": text, "stop_reason": finish, "tool_calls": tool_calls},
            model_name=model,
            # The upstream that actually served it, which for a router is the
            # thing a provenance question is really asking about.
            model_version=str(getattr(response, "provider", "") or getattr(response, "id", "") or ""),
            prompt_hash=content_digest({"system": inputs.get("system", ""), "prompt": prompt, "messages": messages}),
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cost_micros=_cost_micros(usage) if usage else 0,
            cost_currency="USD",
        )

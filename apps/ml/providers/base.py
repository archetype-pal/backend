"""The one interface the rest of the platform talks to.

Callers name a provider; they never import a model client. Swapping, upgrading
or self-hosting a model is then a change in one place — the registry — rather
than at every call site.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """A provider failed. Carries a message safe to store in the ledger."""


@dataclass(frozen=True)
class InferenceRequest:
    """What to run. `inputs` is provider-specific and opaque to the ledger."""

    task: str
    inputs: Mapping[str, Any]
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InferenceResult:
    """What came back, plus everything the ledger needs to record the call.

    Providers report their own cost: only the provider knows its pricing, and a
    cost the platform guesses is worse than no cost at all.
    """

    output: Mapping[str, Any]
    model_name: str
    model_version: str = ""
    prompt_hash: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    cost_currency: str = ""


class InferenceProvider(Protocol):
    """Structural interface — a provider is anything with `run`."""

    def run(self, request: InferenceRequest) -> InferenceResult: ...


def client_limits(request: InferenceRequest) -> dict[str, Any]:
    """Client options for a caller that has to answer someone within a deadline.

    The SDKs wait ten minutes per attempt and retry twice, which suits a batch
    run in a worker. A caller with a person waiting, such as the public agent
    behind a proxy that gives up after a minute, passes `timeout_seconds` in
    `params` and gets that long, once. Read from `params` so the ledger records
    the limit a call was given.
    """
    seconds = request.params.get("timeout_seconds")
    if not seconds:
        return {}
    return {"timeout": float(seconds), "max_retries": 0}

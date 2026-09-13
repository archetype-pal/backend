"""Single declarative source of truth for every corpus pipeline.

Five programme items — W2.1, W2.2, W2.4, W3.2, W3.3 — are the same shape: pick
some corpus material, ask a model about it, propose the answer for review. Each
is therefore one :class:`Pipeline` registration here rather than a module of its
own, in the shape `apps/search/registry.py` and `apps/ml/providers/registry.py`
already use. Adding an item is a single-entry edit; nothing about a pipeline
lives anywhere else.

The runner is the only code that calls the inference service, so the ledger,
the spend caps and the data-policy gate apply to every item automatically —
no item can forget them, because no item does its own calling.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Unit:
    """One piece of corpus material a pipeline runs over."""

    source_type: str
    source_id: int
    # Whatever the prompt builder needs. Never persisted; the ledger stores a
    # digest of it rather than the material itself.
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Pipeline:
    """The complete configuration for one programme item."""

    key: str
    description: str
    # Yields the work. Bounded by the runner's --limit, so a selector may return
    # the whole corpus.
    select: Callable[[], Iterable[Unit]]
    # (unit) -> (system prompt, user prompt)
    prompt: Callable[[Unit], tuple[str, str]]
    # (raw model text) -> a JSON-serialisable payload. Raises ValueError when the
    # model returned something unusable, which the runner records as a failure
    # rather than proposing nonsense.
    parse: Callable[[str], Any]
    # (proposal, reviewer) -> the canonical rows created on acceptance.
    materialise: Callable[..., list[Any]]
    # Overridable per run; None means the provider's configured default.
    model: str | None = None
    max_tokens: int = 4000


PIPELINE_REGISTRY: dict[str, Pipeline] = {}


class UnknownPipeline(LookupError):
    """No pipeline is registered under that key."""


def register(pipeline: Pipeline) -> Pipeline:
    PIPELINE_REGISTRY[pipeline.key] = pipeline
    return pipeline


def resolve(key: str) -> Pipeline:
    try:
        return PIPELINE_REGISTRY[key]
    except KeyError:
        known = ", ".join(sorted(PIPELINE_REGISTRY)) or "(none)"
        raise UnknownPipeline(f"Unknown pipeline '{key}'. Registered: {known}.") from None

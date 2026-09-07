"""Single declarative source of truth for every inference provider.

Each provider name maps to exactly one :class:`ProviderRegistration` holding all
of its configuration. Adding a provider is a single-entry edit here; nothing
about a provider lives anywhere else.

`hosted` is the load-bearing field. The programme's data policy distinguishes
self-hosted vision models — where images never leave our infrastructure — from
hosted models governed by a published policy. Recording that on the registration
rather than in documentation is what lets the policy be *checked* (see
`apps.ml.services.inference`) instead of merely stated.
"""

from collections.abc import Callable
from dataclasses import dataclass

from .base import InferenceProvider
from .null import NullProvider


@dataclass(frozen=True)
class ProviderRegistration:
    """The complete configuration for one provider."""

    name: str
    factory: Callable[[], InferenceProvider]
    # True when inference leaves our infrastructure. Gated by the data policy.
    hosted: bool
    description: str = ""


PROVIDER_REGISTRY: dict[str, ProviderRegistration] = {
    "null": ProviderRegistration(
        name="null",
        factory=NullProvider,
        hosted=False,
        description="Deterministic echo provider. Exercises the ledger without calling a model.",
    ),
}


class UnknownProvider(LookupError):
    """No provider is registered under that name."""


def resolve_provider(name: str) -> ProviderRegistration:
    """Return the registration for *name*, or raise :class:`UnknownProvider`."""
    try:
        return PROVIDER_REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(PROVIDER_REGISTRY)) or "(none)"
        raise UnknownProvider(f"Unknown inference provider '{name}'. Registered: {known}.") from None

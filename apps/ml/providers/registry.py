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
from .claude import ClaudeProvider
from .embedder import EmbedderProvider
from .htr_service import HtrServiceProvider
from .null import NullProvider
from .openrouter import OpenRouterProvider
from .page_search import PageSearchProvider
from .pixels import PixelProvider
from .shape import HogProvider, InkProvider


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
    "openrouter": ProviderRegistration(
        name="openrouter",
        factory=OpenRouterProvider,
        hosted=True,
        description=(
            "OpenRouter — many models behind one key. The default hosted provider. Routes to an "
            "upstream it chooses, so the recipient is not fixed at configuration time; see the "
            "data policy."
        ),
    ),
    "trocr": ProviderRegistration(
        name="trocr",
        factory=EmbedderProvider,
        hosted=False,
        description=(
            "The vision encoder of LaMOP/TrOCR_Manicule_2026_Latin_Medieval (MIT), a handwriting-recognition "
            "model fine-tuned on medieval Latin, run on our own server by the embedder service at "
            "ML_EMBEDDER_URL. Images never leave our infrastructure. Used as published: it has not been "
            "trained on this corpus. Turns glyph crops into 768-d vectors (W1.2, W1.3)."
        ),
    ),
    "kraken": ProviderRegistration(
        name="kraken",
        factory=HtrServiceProvider,
        hosted=False,
        description=(
            "Kraken (Apache-2.0) with CATMuS Medieval 1.5.0 (CC-BY 4.0), an off-the-shelf model for medieval "
            "Latin and vernacular hands, run on our own server by the HTR service at ML_HTR_URL. Images never "
            "leave our infrastructure. Finds a page's lines and reads them, keeping abbreviations as written "
            "(W1.4). Used as published: it has not been trained on this corpus."
        ),
    ),
    "pixels": ProviderRegistration(
        name="pixels",
        factory=PixelProvider,
        hosted=False,
        description=(
            "Not a model: a glyph crop shrunk to 16 × 16 grey pixels. The raw-pixel baseline the "
            "evaluation plan (§9.1) asks for beside any vision model, so that an encoder which has "
            "learned the photograph rather than the letter is caught. Runs in-process, on Pillow."
        ),
    ),
    "ink": ProviderRegistration(
        name="ink",
        factory=InkProvider,
        hosted=False,
        description=(
            "Not a model: a glyph crop binarised by Otsu's threshold and shrunk to 32 × 32, so parchment "
            "tone and ink density drop out and the letter's shape is left. Runs in-process, on Pillow and numpy."
        ),
    ),
    "hog": ProviderRegistration(
        name="hog",
        factory=HogProvider,
        hosted=False,
        description=(
            "Not a model: histograms of oriented gradients over a glyph crop at 48 × 48, which record the "
            "direction of its strokes. Runs in-process, on Pillow and numpy."
        ),
    ),
    "hog-page": ProviderRegistration(
        name="hog-page",
        factory=PageSearchProvider,
        hosted=False,
        description=(
            "Not a model: the `hog` descriptor run over a whole page, scoring every letter-sized window against "
            "examples of a letter already marked there, to propose the rest (W3.4). Runs in-process, on numpy."
        ),
    ),
    "claude": ProviderRegistration(
        name="claude",
        factory=ClaudeProvider,
        hosted=True,
        description=(
            "Anthropic Messages API, called directly. Kept alongside OpenRouter for the features "
            "the OpenAI-compatible surface does not expose — adaptive thinking, server-side "
            "fallbacks, prompt-cache control — which the agent (W3.1) is most likely to want."
        ),
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

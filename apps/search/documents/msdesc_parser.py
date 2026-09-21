"""Facet values parsed out of stored msDesc TEI fragments.

These six have no relational column to read from, so they come from the TEI:

    material      ← supportDesc/@material
    script        ← handNote/@script
    deco_type     ← decoNote/@type
    seal_type     ← seal/@type
    seal_material ← seal/material text
    origin_place  ← origPlace place name, inside an ``origin``

Extraction is area-agnostic: every fragment is scanned for every construct, so a
mislabelled ``area`` column degrades instead of silently zeroing a facet. Two
constructs are context-scoped. ``origPlace`` counts only inside an ``origin``,
being also a phrase leaf the editor can drop into provenance prose; a
``material`` element counts only inside a ``seal``, since the support's own
``<material>`` is free text about parchment.

Never raises: a malformed fragment degrades to no values rather than breaking a
whole-corpus reindex. Matching is by local name, so namespaced fragments behave
like the un-namespaced ones the editor writes. Callers pass published fragments
only.
"""

from collections.abc import Iterable
from functools import lru_cache
import re
import xml.etree.ElementTree as ET

from apps.manuscripts.services.tei.msdesc import (
    DECO_NOTE_TYPES,
    HAND_NOTE_SCRIPTS,
    SEAL_TYPES,
    SUPPORT_DESC_MATERIALS,
)
from apps.search.documents.utils import unique_preserve_order

# Bump when extraction semantics change; the cache key includes it, so stale
# entries evict themselves.
PARSER_VERSION = 3

FACET_KEYS: tuple[str, ...] = (
    "material",
    "script",
    "deco_type",
    "seal_type",
    "seal_material",
    "origin_place",
)

# Fragments are elements, not documents: wrapping lets stray siblings parse
# instead of raising.
_WRAP_OPEN = "<__msdesc_facets_root__>"
_WRAP_CLOSE = "</__msdesc_facets_root__>"

_WHITESPACE_RE = re.compile(r"\s+")

# element local name → (attribute, facet key, ODD vocabulary)
_ATTRIBUTE_FACETS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "supportDesc": ("material", "material", SUPPORT_DESC_MATERIALS),
    "handNote": ("script", "script", HAND_NOTE_SCRIPTS),
    "decoNote": ("type", "deco_type", DECO_NOTE_TYPES),
}

# Most specific first: one origPlace yields one facet value, so a record giving
# both country and settlement facets on the settlement.
_ORIG_PLACE_CHILDREN: tuple[str, ...] = ("settlement", "region", "country")


def extract_msdesc_facets(fragments: Iterable[str]) -> dict[str, list[str]]:
    """Return ``{facet key: values}`` for the msDesc *fragments* supplied.

    Values are de-duplicated with a stable order (fragment order, then document
    order within a fragment). Facets with no values are omitted entirely rather
    than emitted as empty lists. Callers must pass **published** fragments only.
    """
    collected: dict[str, list[str]] = {}
    for fragment in fragments:
        if not isinstance(fragment, str) or not fragment.strip():
            continue
        for key, value in _extract_fragment_cached(fragment, PARSER_VERSION):
            collected.setdefault(key, []).append(value)
    return {key: unique_preserve_order(collected[key]) for key in FACET_KEYS if collected.get(key)}


# A reindex walks the fragments in a fixed cycle, and an LRU smaller than a
# cyclic working set evicts every entry before its next use. The ceiling is
# 4 areas x item parts (2852 today); revisit past ~1000 item parts.
_FRAGMENT_CACHE_SIZE = 4096


@lru_cache(maxsize=_FRAGMENT_CACHE_SIZE)
def _extract_fragment_cached(fragment: str, version: int) -> tuple[tuple[str, str], ...]:
    """Parse one fragment into ``(facet key, value)`` pairs, in document order.

    Cached because every `MsDescArea` save enqueues a *full* item-parts reindex:
    consecutive rebuilds re-feed the same fragments, of which at most one has
    changed. Cache is per worker process (in-process); the return value is
    immutable so cache entries can't be mutated by a caller.
    """
    del version  # only here to participate in the cache key
    try:
        root = ET.fromstring(f"{_WRAP_OPEN}{fragment}{_WRAP_CLOSE}")
    except ET.ParseError:
        return ()

    values: list[tuple[str, str]] = []
    for element in root.iter():
        name = _local_name(element.tag)
        attribute_facet = _ATTRIBUTE_FACETS.get(name)
        if attribute_facet is not None:
            attribute, key, vocabulary = attribute_facet
            value = _normalize(element.get(attribute))
            if value:
                values.append((key, _canonical_vocabulary_value(value, vocabulary)))
        elif name == "seal":
            seal_type = _normalize(element.get("type"))
            if seal_type:
                values.append(("seal_type", _canonical_vocabulary_value(seal_type, SEAL_TYPES)))
            for child in element:
                if _local_name(child.tag) != "material":
                    continue
                material = _element_text(child)
                if material:
                    values.append(("seal_material", material))
        elif name == "origin":
            # `origPlace` is a phrase leaf the editor can also drop into
            # provenance prose, where it is not a place of origin.
            for descendant in element.iter():
                if _local_name(descendant.tag) != "origPlace":
                    continue
                place = _origin_place_name(descendant)
                if place:
                    values.append(("origin_place", place))
    return tuple(values)


def _origin_place_name(element) -> str:
    """Most specific named place inside an ``origPlace``, else its own text."""
    texts: dict[str, str] = {}
    for child in element:
        name = _local_name(child.tag)
        if name in _ORIG_PLACE_CHILDREN and name not in texts:
            text = _element_text(child)
            if text:
                texts[name] = text
    for name in _ORIG_PLACE_CHILDREN:
        if name in texts:
            return texts[name]
    return _element_text(element)


def _element_text(element) -> str:
    """Whitespace-collapsed text of *element* including descendants (e.g. ``<ref>``)."""
    return _normalize("".join(element.itertext()))


def _local_name(tag) -> str:
    """Namespace-stripped element name (``''`` for comments/PIs, whose tag is callable)."""
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def _normalize(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", value or "").strip()


def _canonical_vocabulary_value(value: str, vocabulary: tuple[str, ...]) -> str:
    """Canonicalise *value* against an ODD vocabulary, passing unknowns through.

    A value that matches a `msdesc.py` vocabulary item apart from case is
    indexed with the ODD's spelling, so ``@material="Perg"`` doesn't split the
    facet away from ``"perg"``. Anything else is indexed exactly as authored:
    most of these lists are ``type="semi"`` (open by design), and silently
    dropping an unlisted value would hide the record from its own facet.
    """
    if value in vocabulary:
        return value
    lowered = value.lower()
    for candidate in vocabulary:
        if candidate.lower() == lowered:
            return candidate
    return value

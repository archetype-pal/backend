"""Extract facet values from stored msDesc TEI fragments (TEI-descriptions 7.1).

``MsDescArea.content`` holds a TEI *element fragment* rooted at one of the four
msDesc areas. Only four facets have no relational column to read from, so only
those are parsed out of the TEI here:

    material     ← supportDesc/@material          (physDesc area)
    script       ← handNote/@script               (physDesc area)
    deco_type    ← decoNote/@type                 (physDesc area)
    origin_place ← origPlace place name, inside an ``origin``  (history area)

The area in brackets says where each construct *belongs*; it is **not** a
dispatch rule. Extraction is deliberately area-agnostic: every published
fragment is scanned for all four constructs, so a mislabelled ``area`` column
degrades gracefully instead of silently zeroing a facet. On well-formed data
the result is identical, since these constructs only occur in their own area.
``origPlace`` is the one construct that *is* context-scoped — it counts only
inside an ``origin`` — because it is also a phrase leaf the rich editor can
drop inline into provenance prose, where it names a later location rather than
the place of origin.

Everything a facet could also want — date, format, repository, shelfmark — is
already a relational column and is read there by ``item_parts.py``; re-parsing
it out of TEI would duplicate the source of truth (the roadmap rejects this
explicitly for origin *dates*: ``HistoricalItem.date`` covers the whole corpus).

Parsing is stdlib-only (``xml.etree.ElementTree``, as in
``services/tei/validate.py``) and **never raises**: a malformed or unexpected
fragment degrades to "no facet values" so one bad description cannot break a
whole-corpus reindex. Element matching is by local name, so a fragment that
carries a TEI namespace behaves the same as the un-namespaced fragments the
editor writes.

Publication gating is the *caller's* job — see ``item_parts.py``, which passes
published fragments only.
"""

from collections.abc import Iterable
from functools import lru_cache
import re
import xml.etree.ElementTree as ET

from apps.manuscripts.services.tei.msdesc import (
    DECO_NOTE_TYPES,
    HAND_NOTE_SCRIPTS,
    SUPPORT_DESC_MATERIALS,
)
from apps.search.documents.utils import unique_preserve_order

# Bump when extraction semantics change (new element/attribute, different
# whitespace handling, …). The cache key includes this version, so old entries
# evict naturally on the first call after a bump — no manual flush.
PARSER_VERSION = 2

# The document keys this module can emit, in the order they appear in a doc.
FACET_KEYS: tuple[str, ...] = ("material", "script", "deco_type", "origin_place")

# Fragments are element fragments, not documents; wrap before parsing so stray
# siblings/text parse instead of raising (same idiom as `validate_tei_wellformed`).
_WRAP_OPEN = "<__msdesc_facets_root__>"
_WRAP_CLOSE = "</__msdesc_facets_root__>"

_WHITESPACE_RE = re.compile(r"\s+")

# element local name → (attribute, facet key, ODD vocabulary)
_ATTRIBUTE_FACETS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "supportDesc": ("material", "material", SUPPORT_DESC_MATERIALS),
    "handNote": ("script", "script", HAND_NOTE_SCRIPTS),
    "decoNote": ("type", "deco_type", DECO_NOTE_TYPES),
}

# origPlace children, most specific first: one origPlace contributes one facet
# value, so a record giving country + settlement facets on the settlement rather
# than on both granularities at once.
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


# Sized above the corpus ceiling — `MsDescArea` is unique on (item_part, area),
# so a fully catalogued corpus presents at most `4 areas × item parts` distinct
# fragments (713 parts today ⇒ 2852). A full reindex walks them in a fixed cycle,
# and an LRU smaller than a cyclic working set evicts every entry before its next
# use (~0% hits). Revisit this number if the corpus passes ~1000 item parts.
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
        elif name == "origin":
            # Scoped to `origin` (at any depth, so `<origin><p>… <origPlace/></p>`
            # still counts): `origPlace` is a phrase leaf the rich editor can also
            # drop into provenance prose, where it is not a place of origin.
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

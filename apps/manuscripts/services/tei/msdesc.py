"""msDesc area names + controlled vocabularies.

The backend analog of the frontend's `lib/msdesc-vocab.ts`: one transcription of
the `valItem` lists in `msdesc-minimal/msdesc-minimal.odd` (repo root) so
server-side consumers — the export envelope, the facet extractor — never
re-derive them. Values are the canonical TEI attribute values exactly as the
ODD spells them (e.g. ``@material="perg"``); display labels and i18n live
frontend-side. Pure data: no Django imports.

Update this module only in lockstep with the ODD — its valItem lists are
authoritative.
"""

# The four msDesc areas a description is stored under (one `MsDescArea` row
# each, rooted at the same-named TEI element). Order follows the msDesc content
# model: msIdentifier, msContents, physDesc, history.
MSDESC_AREAS: tuple[str, ...] = (
    "msIdentifier",
    "msContents",
    "physDesc",
    "history",
)

# supportDesc/@material (valList mode="replace" type="closed").
SUPPORT_DESC_MATERIALS: tuple[str, ...] = (
    "perg",
    "chart",
    "papyrus",
    "palm",
    "mixed",
    "other",
    "unknown",
)

# handNote/@script (valList mode="replace" type="semi") — the Bodleian–Cambridge
# controlled script names.
HAND_NOTE_SCRIPTS: tuple[str, ...] = (
    "capitalsSquare",
    "capitalsRustic",
    "uncial",
    "halfUncial",
    "minusculeInsular",
    "minusculeVernacular",
    "minusculeCaroline",
    "minuscule",
    "protogothic",
    "textualisNorthern",
    "textualisSouthern",
    "semitextualis",
    "cursivaAntiquior",
    "cursiva",
    "hybrida",
    "gothicoAntiqua",
    "humanisticaTextualis",
    "humanisticaSemitextualis",
    "humanisticaCursiva",
)

# decoNote/@type (valList mode="replace" type="semi").
DECO_NOTE_TYPES: tuple[str, ...] = (
    "border",
    "diagram",
    "drawing",
    "histInit",
    "decInit",
    "flourInit",
    "colInit",
    "plainInit",
    "illustration",
    "initial",
    "marginal",
    "miniature",
    "rubrication",
    "bas-de-page",
    "map",
    "headpiece",
    "chrysography",
    "lineFill",
    "cadel",
    "instructions",
    "unfilled",
    "none",
    "other",
)

# seal/@type. NOT from the ODD — `msdesc-minimal` derives from a book/codex
# schema and models no seals. Kept in step with `frontend/lib/msdesc-vocab.ts`
# SEAL_TYPES; the form makes anything outside this list unrepresentable.
SEAL_TYPES: tuple[str, ...] = (
    "greatSeal",
    "privySeal",
    "secretum",
    "signet",
    "counterseal",
    "other",
)

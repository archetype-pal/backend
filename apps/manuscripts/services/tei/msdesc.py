"""msDesc area names + controlled vocabularies (TEI-descriptions Phase 0.2).

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

# objectDesc/@form (valList mode="replace" type="closed").
OBJECT_DESC_FORMS: tuple[str, ...] = (
    "codex",
    "roll",
    "sheet",
    "faltbuch",
    "roll-codex",
    "other",
    "unknown",
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

# handNote/@execution (valList mode="semi") — the consolidated-msdesc addition
# recording the grade of execution (formality) of the script.
HAND_NOTE_EXECUTIONS: tuple[str, ...] = (
    "formata",
    "libraria",
    "currens",
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

# availability/@status (valList mode="replace" type="semi").
AVAILABILITY_STATUSES: tuple[str, ...] = (
    "free",
    "restricted",
    "exhibition",
    "offsite",
    "printcat",
    "none",
    "unknown",
)

# layout/@topLine (valList mode="closed" type="closed").
LAYOUT_TOP_LINES: tuple[str, ...] = (
    "above",
    "below",
    "mixed",
)

# layout/@rulingMedium — the ODD declares this teidata.text with suggested
# values only (semi-open, listed in an ODD comment rather than valItems), so
# unlike the lists above a value outside this tuple is still schema-legal.
LAYOUT_RULING_MEDIA: tuple[str, ...] = (
    "leadpoint",
    "hardpoint",
    "ink",
    "drypoint",
    "crayon",
    "mixed",
    "unknown",
)

# Aggregate view keyed by "element@attribute", for consumers that iterate the
# vocabularies generically (e.g. a facet extractor) instead of importing each
# tuple by name.
MSDESC_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "objectDesc@form": OBJECT_DESC_FORMS,
    "supportDesc@material": SUPPORT_DESC_MATERIALS,
    "handNote@script": HAND_NOTE_SCRIPTS,
    "handNote@execution": HAND_NOTE_EXECUTIONS,
    "decoNote@type": DECO_NOTE_TYPES,
    "availability@status": AVAILABILITY_STATUSES,
    "layout@topLine": LAYOUT_TOP_LINES,
    "layout@rulingMedium": LAYOUT_RULING_MEDIA,
}

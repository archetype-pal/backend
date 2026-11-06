"""Assemble a part's msDesc areas (and linked-prose descriptions) into a TEI P5 document."""

from dataclasses import dataclass, field

from apps.manuscripts.models import ItemPart

from .description import tei_description_body
from .document import wrap_msdesc_document
from .validate import validate_tei_wellformed


@dataclass
class MsDescExport:
    #: The assembled document, or None when no area survived.
    document: str | None
    #: Well-formedness errors per area (or `description[i]`), for the fragments that were skipped.
    malformed: dict[str, list[dict]] = field(default_factory=dict)


def export_msdesc(part: ItemPart, *, published_only: bool) -> MsDescExport:
    """Build the TEI document for `part`, skipping fragments that are not well-formed XML.

    Nothing on the write path enforces well-formedness and the wrapper inserts
    content verbatim, so one malformed draft would otherwise make the whole
    download unparseable. Filtering happens in Python over `.all()` so a
    caller's `msdesc_areas` prefetch is reused. Legacy HTML descriptions are
    skipped, not converted: they are not TEI.
    """
    fragments: dict[str, str] = {}
    malformed: dict[str, list[dict]] = {}
    for area in part.msdesc_areas.all():
        content = (area.content or "").strip()
        if not content or (published_only and not area.is_published):
            continue
        if errors := validate_tei_wellformed(content):
            malformed[area.area] = errors
        else:
            fragments[area.area] = content

    descriptions: list[str] = []
    for index, row in enumerate(part.historical_item.descriptions.all()):
        body = tei_description_body(row.content or "")
        if body is None:
            continue
        if errors := validate_tei_wellformed(body):
            malformed[f"description[{index}]"] = errors
        else:
            descriptions.append(body)

    if not fragments:
        return MsDescExport(document=None, malformed=malformed)
    document = wrap_msdesc_document(
        fragments,
        title=part.display_label(),
        source_note=f"Archetype ItemPart #{part.pk}.",
        descriptions=descriptions,
    )
    return MsDescExport(document=document, malformed=malformed)

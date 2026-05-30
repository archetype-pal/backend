"""Shared HTR line model + TEI builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape


def local_name(tag: str) -> str:
    """Strip an XML namespace from a tag (e.g. ``{ns}TextLine`` -> ``TextLine``)."""
    return tag.rsplit("}", 1)[-1]


@dataclass
class HtrLine:
    text: str
    # Polygon ring as [[x, y], ...] in image pixels, or empty if none.
    points: list[list[float]] = field(default_factory=list)

    def geojson(self) -> dict | None:
        if not self.points:
            return None
        ring = [list(p) for p in self.points]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]}}


def lines_to_tei(lines: list[HtrLine], *, graph_ids: list[int | None] | None = None) -> str:
    """Build a TEI body from HTR lines.

    Each line becomes `<seg type="line">…</seg>` followed by `<lb/>`; when a
    matching graph id is supplied it is attached as `corresp="#gid-N"`.
    """
    parts: list[str] = ["<p>"]
    for i, line in enumerate(lines):
        gid = graph_ids[i] if graph_ids and i < len(graph_ids) else None
        corresp = f' corresp="#gid-{gid}"' if gid else ""
        parts.append(f'<seg type="line"{corresp}>{escape(line.text)}</seg><lb/>')
    parts.append("</p>")
    return "".join(parts)

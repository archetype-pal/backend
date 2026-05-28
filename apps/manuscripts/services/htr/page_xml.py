"""PAGE-XML → HtrLine parser (namespace-agnostic)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .builder import HtrLine


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_points(value: str) -> list[list[float]]:
    points: list[list[float]] = []
    for token in (value or "").split():
        if "," in token:
            x, _, y = token.partition(",")
            try:
                points.append([float(x), float(y)])
            except ValueError:
                continue
    return points


def page_xml_to_lines(xml: str) -> list[HtrLine]:
    """Extract ordered text lines (with Coords polygons) from a PAGE-XML doc."""
    root = ET.fromstring(xml)
    lines: list[HtrLine] = []
    for el in root.iter():
        if _local(el.tag) != "TextLine":
            continue
        text = ""
        points: list[list[float]] = []
        for child in el:
            name = _local(child.tag)
            if name == "Coords":
                points = _parse_points(child.get("points", ""))
            elif name == "TextEquiv":
                unicode_el = next((g for g in child if _local(g.tag) == "Unicode"), None)
                if unicode_el is not None and unicode_el.text:
                    text = unicode_el.text.strip()
        if text or points:
            lines.append(HtrLine(text=text, points=points))
    return lines

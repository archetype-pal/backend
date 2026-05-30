"""ALTO XML → HtrLine parser (namespace-agnostic)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .builder import HtrLine


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _bbox_polygon(el: ET.Element) -> list[list[float]]:
    hpos, vpos, width, height = el.get("HPOS"), el.get("VPOS"), el.get("WIDTH"), el.get("HEIGHT")
    if hpos is None or vpos is None or width is None or height is None:
        return []
    try:
        x = float(hpos)
        y = float(vpos)
        w = float(width)
        h = float(height)
    except ValueError:
        return []
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]


def alto_to_lines(xml: str) -> list[HtrLine]:
    """Extract ordered text lines from an ALTO doc; geometry from the line bbox."""
    root = ET.fromstring(xml)
    lines: list[HtrLine] = []
    for el in root.iter():
        if _local(el.tag) != "TextLine":
            continue
        words: list[str] = []
        for child in el.iter():
            if _local(child.tag) == "String":
                content = child.get("CONTENT")
                if content:
                    words.append(content)
        text = " ".join(words).strip()
        points = _bbox_polygon(el)
        if text or points:
            lines.append(HtrLine(text=text, points=points))
    return lines

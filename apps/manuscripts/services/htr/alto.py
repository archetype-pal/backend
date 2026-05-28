"""ALTO XML → HtrLine parser (namespace-agnostic)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .builder import HtrLine


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _bbox_polygon(el: ET.Element) -> list[list[float]]:
    try:
        x = float(el.get("HPOS"))
        y = float(el.get("VPOS"))
        w = float(el.get("WIDTH"))
        h = float(el.get("HEIGHT"))
    except TypeError, ValueError:
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

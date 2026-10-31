"""Extract clauses, places and people from ``ImageText.content``.

The stored form is TEI (``<seg type>``, ``<persName>``, ``<placeName>``, linked
to an image region by ``corresp="#gid-N"``); a corpus that has not been through
the DigiPal migration still carries the older ``data-dpt`` spans. Both are read
natively — there is no conversion step — so one parse serves the texts, clauses,
people and places builders.
"""

from functools import lru_cache
from html.parser import HTMLParser

from apps.common.text import collapse_whitespace

# TEI element (lower-cased by HTMLParser) -> the kind of mention it marks up.
_TEI_KINDS = {"seg": "clause", "persname": "person", "placename": "place"}
_DPT_KINDS = {"clause", "person", "place"}


def _first_graph_id(corresp: str, data_graph_id: str) -> int | None:
    """The first linked region id, from TEI `corresp="#gid-12 #gid-34"` or legacy `data-graph-id="12,34"`."""
    for token in corresp.split():
        digits = token.removeprefix("#").removeprefix("gid-")
        if digits.isdigit():
            return int(digits)
    first = data_graph_id.split(",")[0].strip()
    return int(first) if first.isdigit() else None


class _DptExtractor(HTMLParser):
    """Single-pass parser collecting clause / place / person mentions with their text, type, ref and region."""

    def __init__(self) -> None:
        super().__init__()
        self.clauses: list[dict] = []  # {'type': str, 'content': str, 'annotation_id': int | None}
        self.places: list[dict] = []  # {'name': str, 'type': str, 'ref': str, 'annotation_id': int | None}
        self.people: list[dict] = []  # {'name': str, 'type': str, 'ref': str, 'annotation_id': int | None}
        self._stack: list[dict | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {key: value or "" for key, value in attrs}
        kind = _TEI_KINDS.get(tag)
        if kind is None and tag == "span" and attr_dict.get("data-dpt") in _DPT_KINDS:
            kind = attr_dict["data-dpt"]
        if kind is None:
            self._stack.append(None)
            return
        self._stack.append(
            {
                "dpt": kind,
                "type": attr_dict.get("type") or attr_dict.get("data-dpt-type", ""),
                "ref": attr_dict.get("ref") or attr_dict.get("data-dpt-ref", ""),
                "annotation_id": _first_graph_id(attr_dict.get("corresp", ""), attr_dict.get("data-graph-id", "")),
                "text": "",
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        entry = self._stack.pop()
        if entry is None:
            return
        text = collapse_whitespace(entry["text"])
        if entry["dpt"] == "clause" and text:
            self.clauses.append({"type": entry["type"], "content": text, "annotation_id": entry["annotation_id"]})
        elif entry["dpt"] == "place" and text:
            self.places.append(
                {
                    "name": text,
                    "type": entry["type"],
                    "ref": entry["ref"],
                    "annotation_id": entry["annotation_id"],
                }
            )
        elif entry["dpt"] == "person" and text:
            self.people.append(
                {
                    "name": text,
                    "type": entry["type"],
                    "ref": entry["ref"],
                    "annotation_id": entry["annotation_id"],
                }
            )

    def handle_data(self, data: str) -> None:
        for entry in reversed(self._stack):
            if entry is not None:
                entry["text"] += data
                break


@lru_cache(maxsize=4096)
def _run_extractor(html_content: str) -> _DptExtractor:
    """Parse *html_content* and return the populated extractor.

    Cached because each ImageText is fed through four builders (texts /
    clauses / places / people) during a full reindex; every call after the
    first hits the cache, so a row is parsed once per worker per rebuild.
    """
    extractor = _DptExtractor()
    extractor.feed(html_content)
    return extractor


def extract_clauses(html_content: str) -> list[dict]:
    """Return a list of clause dicts extracted from *html_content*.

    Each dict has the shape ``{'type': str, 'content': str, 'annotation_id': int | None}``
    where *type* comes from the ``data-dpt-type`` attribute (e.g. ``"address"``,
    ``"disposition"``) and *content* is the plain-text of the clause with
    HTML tags stripped and whitespace collapsed.
    """
    return _run_extractor(html_content).clauses


def extract_places_detailed(html_content: str) -> list[dict]:
    """Return place dicts from ``data-dpt='place'`` spans.

    Each dict has the shape ``{'name': str, 'type': str, 'ref': str, 'annotation_id': int | None}`` where
    *type* comes from ``data-dpt-type`` and *ref* from ``data-dpt-ref``
    (an authority URI such as a GeoNames link).
    """
    return _run_extractor(html_content).places


def extract_people_detailed(html_content: str) -> list[dict]:
    """Return person dicts from ``data-dpt='person'`` spans.

    Each dict has the shape ``{'name': str, 'type': str, 'ref': str, 'annotation_id': int | None}`` where
    *type* comes from ``data-dpt-type`` (e.g. ``"name"``, ``"title"``) and
    *ref* from ``data-dpt-ref`` (an authority URI such as a VIAF link).
    """
    return _run_extractor(html_content).people


def extract_all(html_content: str) -> dict:
    """Parse once and return all extracted elements.

    Returns::

        {
            'clauses': [{'type': str, 'content': str}, ...],
            'places': [{'name': str, 'type': str, 'ref': str}, ...],
            'people': [{'name': str, 'type': str, 'ref': str}, ...],
        }
    """
    ext = _run_extractor(html_content)
    return {
        "clauses": ext.clauses,
        "places": ext.places,
        "people": ext.people,
    }

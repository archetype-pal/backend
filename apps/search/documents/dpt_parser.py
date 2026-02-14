"""Extract structured elements from data-dpt HTML markup in ImageText content.

The legacy system uses ``data-dpt`` attributes on ``<span>`` elements to mark
up clauses, places, and people inside transcription/translation HTML.  This
module provides a single-pass HTML parser that collects those elements so they
can be indexed in Meilisearch.

Recognised ``data-dpt`` values (matching the legacy whitelist):
    clause, place, person

Supported attributes on each span:
    data-dpt       – element type (clause | place | person)
    data-dpt-type  – sub-type (e.g. "address", "name", "region")
    data-dpt-cat   – category ("words" | "chars")
    data-dpt-ref   – authority/canonical reference (e.g. VIAF URI, GeoNames URI)
"""

from html.parser import HTMLParser
import re


class _DptExtractor(HTMLParser):
    """Single-pass HTML parser that collects ``data-dpt`` elements.

    Internally stores rich dicts for every element type.  Public helper
    functions decide what shape to expose to callers.
    """

    def __init__(self) -> None:
        super().__init__()
        self.clauses: list[dict] = []  # {'type': str, 'content': str}
        self.places: list[dict] = []  # {'name': str, 'type': str, 'ref': str}
        self.people: list[dict] = []  # {'name': str, 'type': str, 'ref': str}
        self._stack: list[dict | None] = []

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        dpt = attr_dict.get("data-dpt")
        if dpt in ("clause", "place", "person"):
            self._stack.append(
                {
                    "dpt": dpt,
                    "type": attr_dict.get("data-dpt-type", ""),
                    "ref": attr_dict.get("data-dpt-ref", ""),
                    "text": "",
                }
            )
        else:
            self._stack.append(None)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        entry = self._stack.pop()
        if entry is None:
            return
        text = re.sub(r"\s+", " ", entry["text"]).strip()
        if entry["dpt"] == "clause":
            self.clauses.append({"type": entry["type"], "content": text})
        elif entry["dpt"] == "place" and text:
            self.places.append({"name": text, "type": entry["type"], "ref": entry["ref"]})
        elif entry["dpt"] == "person" and text:
            self.people.append({"name": text, "type": entry["type"], "ref": entry["ref"]})

    def handle_data(self, data: str) -> None:
        # Bubble text up to the nearest data-dpt ancestor on the stack.
        for entry in reversed(self._stack):
            if entry is not None:
                entry["text"] += data
                break


# ------------------------------------------------------------------
# Public helpers
# ------------------------------------------------------------------


def _run_extractor(html_content: str) -> _DptExtractor:
    """Parse *html_content* and return the populated extractor."""
    extractor = _DptExtractor()
    extractor.feed(html_content)
    return extractor


def extract_clauses(html_content: str) -> list[dict]:
    """Return a list of clause dicts extracted from *html_content*.

    Each dict has the shape ``{'type': str, 'content': str}`` where *type*
    comes from the ``data-dpt-type`` attribute (e.g. ``"address"``,
    ``"disposition"``) and *content* is the plain-text of the clause with
    HTML tags stripped and whitespace collapsed.
    """
    return _run_extractor(html_content).clauses


def extract_places(html_content: str) -> list[str]:
    """Return a deduplicated list of place names from ``data-dpt='place'`` spans."""
    return list(dict.fromkeys(p["name"] for p in _run_extractor(html_content).places))


def extract_people(html_content: str) -> list[str]:
    """Return a deduplicated list of person names from ``data-dpt='person'`` spans."""
    return list(dict.fromkeys(p["name"] for p in _run_extractor(html_content).people))


def extract_places_detailed(html_content: str) -> list[dict]:
    """Return place dicts from ``data-dpt='place'`` spans.

    Each dict has the shape ``{'name': str, 'type': str, 'ref': str}`` where
    *type* comes from ``data-dpt-type`` and *ref* from ``data-dpt-ref``
    (an authority URI such as a GeoNames link).
    """
    return _run_extractor(html_content).places


def extract_people_detailed(html_content: str) -> list[dict]:
    """Return person dicts from ``data-dpt='person'`` spans.

    Each dict has the shape ``{'name': str, 'type': str, 'ref': str}`` where
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

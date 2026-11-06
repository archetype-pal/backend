"""Export formats for search results: rows for CSV/JSON, and BibTeX entries."""

from dataclasses import replace
from typing import Any

from apps.search.services import SearchService
from apps.search.types import IndexType, SearchQuery

BIBTEX_INDEXES = (IndexType.ITEM_PARTS, IndexType.SCRIBES, IndexType.HANDS)


def collect_export_rows(
    service: SearchService, index: IndexType, query: SearchQuery, *, scope: str, max_rows: int = 2000
) -> list[dict[str, Any]]:
    if scope != "all":
        return service.search(index, query).hits

    # Page at the Meilisearch max, not the request's display limit (often 20),
    # or a full-corpus export costs ~100 round-trips.
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < max_rows:
        page = service.search(index, replace(query, limit=200, offset=offset))
        if not page.hits:
            break
        rows.extend(page.hits)
        offset += page.limit
        if len(rows) >= page.total:
            break
    return rows[:max_rows]


def csv_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    """Every key in first-seen order, minus Meilisearch's `_formatted` highlight copy."""
    seen: dict[str, None] = {}
    for row in rows:
        if isinstance(row, dict):
            seen.update(dict.fromkeys(key for key in row if key != "_formatted"))
    return list(seen)


def _bibtex_key(*parts: object) -> str:
    return "_".join(str(part or "").strip().replace(" ", "_") for part in parts).replace("/", "_")


def to_bibtex(rows: list[dict[str, Any]], index: IndexType = IndexType.ITEM_PARTS) -> str:
    """`@misc` entries — one per hit — keyed so two exports of the same record collide on purpose."""
    entries: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if index == IndexType.SCRIBES:
            year = row.get("period") or "n.d."
            key = _bibtex_key("scribe", row.get("name") or "unknown", year)
            title = f"Scribe: {row.get('name') or ''}"
            note = f"Scriptorium: {row.get('scriptorium') or 'unknown'}"
            fields = [f"  author = {{{row.get('name') or ''}}},", f"  title = {{{title}}},"]
        elif index == IndexType.HANDS:
            year = row.get("date") or "n.d."
            name = row.get("name") or "unknown"
            key = _bibtex_key("hand", row.get("repository_name") or "repo", name, year)
            note = f"Shelfmark: {row.get('shelfmark') or ''}, Place: {row.get('place') or ''}"
            fields = [f"  title = {{{name}}},", f"  institution = {{{row.get('repository_name') or ''}}},"]
        else:
            year = row.get("date") or row.get("date_min") or "n.d."
            shelfmark = row.get("shelfmark") or row.get("display_label") or "unknown"
            key = _bibtex_key(row.get("repository_name") or "repo", shelfmark, year)
            note = f"Shelfmark: {row.get('shelfmark') or ''}"
            fields = [
                f"  title = {{{row.get('display_label') or shelfmark}}},",
                f"  institution = {{{row.get('repository_name') or ''}}},",
            ]
        entries.append("\n".join([f"@misc{{{key},", *fields, f"  note = {{{note}}},", f"  year = {{{year}}},", "}"]))
    return "\n\n".join(entries)

"""CSV rendering shared by the management and search exports."""

import csv
import io
from typing import Any

# Excel/Sheets treat a cell starting with one of these as a formula; a
# researcher-edited string such as `=cmd|'/c calc'!A1` would execute when an
# admin opens the export. A leading single quote makes the cell literal text.
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    if isinstance(value, str) and value.startswith(_CSV_DANGEROUS_PREFIXES):
        return "'" + value
    return str(value)


def to_csv(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: csv_cell(row.get(name)) for name in fieldnames})
    return buffer.getvalue()

"""CSV rendering shared by the management and search exports."""

import csv
import io
from typing import Any

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework.request import Request

from apps.common.exceptions import BadRequest

# Excel/Sheets treat a cell starting with one of these as a formula; a
# researcher-edited string such as `=cmd|'/c calc'!A1` would execute when an
# admin opens the export. A leading single quote makes the cell literal text.
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def attachment_response(content: str | bytes, content_type: str, filename: str) -> HttpResponse:
    """A file download; a non-ASCII name gets the RFC 5987 ``filename*`` form as well."""
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(True, filename)
    return response


def export_format(request: Request, allowed: tuple[str, ...], default: str = "csv") -> str:
    """``?export_format=`` (or ``?format=``), lower-cased, or a 400 when it is not in *allowed*."""
    raw = request.query_params.get("export_format") or request.query_params.get("format")
    fmt = (raw or default).strip().lower()
    if fmt not in allowed:
        raise BadRequest("Unsupported export format.")
    return fmt


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

"""Pieces shared by the public and management view modules."""

from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.common.exceptions import BadRequest
from apps.common.exports import attachment_response
from apps.manuscripts.models import ImageText, ItemPart
from apps.manuscripts.services.tei.export import export_msdesc

# URL segment -> ImageText.Type, for the per-image "sole text" routes.
KIND_BY_SLUG: dict[str, str] = {kind.lower(): kind for kind in ImageText.Type.values}


def kind_from_slug(slug: str) -> str:
    """The ``ImageText.Type`` behind a per-image route segment, or a 400."""
    try:
        return KIND_BY_SLUG[slug]
    except KeyError:
        raise BadRequest("Unknown kind.") from None


def tei_attachment(document: str, filename: str) -> HttpResponse:
    return attachment_response(document, "application/tei+xml; charset=utf-8", filename)


def msdesc_tei_response(part: ItemPart, *, published_only: bool) -> HttpResponse:
    """Serve a part's msDesc areas as an attached TEI P5 document.

    Shared by the public and management `tei/` actions; `published_only` is the
    entire difference between them. The two audiences want opposite handling
    of a malformed fragment, so they get it: the public download SKIPS it (a
    single bad fragment must not break an otherwise-published record, and the
    caller cannot fix it anyway), the editorial one refuses with 422 and the
    per-area errors so a cataloguer sees exactly what to repair.

    404 when nothing is exportable: `<msDesc>` requires an `msIdentifier`, so
    an areas-less document would be a schema-invalid stub.
    """
    result = export_msdesc(part, published_only=published_only)
    if result.malformed and not published_only:
        return Response(
            {
                "detail": "Some msDesc areas are not well-formed XML, so no TEI document can be assembled.",
                "errors": result.malformed,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if result.document is None:
        detail = "No published, well-formed msDesc areas." if published_only else "No msDesc areas."
        raise NotFound(detail)
    return tei_attachment(result.document, f"itempart-{part.pk}-msdesc.tei")

"""Tests for the convert-on-read TEI download endpoint (Phase H.12)."""

import pytest

from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory

pytestmark = pytest.mark.django_db

DPT_CONTENT = (
    '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation" data-graph-id="2824">salutem</span></p>'
)


def _url(pk: int) -> str:
    return f"/api/v1/manuscripts/image-texts/{pk}/tei/"


def test_tei_download_returns_wrapped_document(api_client):
    image = ItemImageFactory(locus="fol. 1r")
    text = ImageText.objects.create(
        item_image=image,
        content=DPT_CONTENT,
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )

    response = api_client.get(_url(text.id))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/tei+xml")
    assert response["Content-Disposition"] == f'attachment; filename="imagetext-{text.id}.tei"'
    body = response.content.decode()
    assert body.startswith('<?xml version="1.0"')
    assert "<TEI " in body and "<teiHeader>" in body
    # data-dpt converted to TEI; the link rides along as corresp.
    assert '<seg type="salutation" corresp="#gid-2824">salutem</seg>' in body
    assert "data-dpt" not in body
    assert "Transcription — fol. 1r" in body


def test_tei_download_hidden_from_anonymous_for_draft(api_client):
    image = ItemImageFactory()
    draft = ImageText.objects.create(
        item_image=image,
        content=DPT_CONTENT,
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    assert api_client.get(_url(draft.id)).status_code == 404


def test_tei_download_visible_to_staff_for_draft(management_client):
    image = ItemImageFactory()
    draft = ImageText.objects.create(
        item_image=image,
        content=DPT_CONTENT,
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )

    response = management_client.get(_url(draft.id))
    assert response.status_code == 200
    assert "<TEI " in response.content.decode()

"""Tests for HTR import (PAGE-XML / ALTO → TEI) and the import endpoint (C3)."""

import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.services.htr import alto_to_lines, lines_to_tei, page_xml_to_lines
from apps.manuscripts.tests.factories import ItemImageFactory

PAGE_XML = """<?xml version="1.0"?>
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15">
  <Page>
    <TextRegion>
      <TextLine><Coords points="10,20 110,20 110,60 10,60"/>
        <TextEquiv><Unicode>Omnibus sancte</Unicode></TextEquiv></TextLine>
      <TextLine><Coords points="10,70 120,70 120,110 10,110"/>
        <TextEquiv><Unicode>matris ecclesie</Unicode></TextEquiv></TextLine>
    </TextRegion>
  </Page>
</PcGts>"""

ALTO_XML = """<?xml version="1.0"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#">
  <Layout><Page><PrintSpace>
    <TextBlock>
      <TextLine HPOS="10" VPOS="20" WIDTH="100" HEIGHT="40">
        <String CONTENT="Omnibus"/><SP/><String CONTENT="sancte"/>
      </TextLine>
    </TextBlock>
  </PrintSpace></Page></Layout>
</alto>"""


def test_page_xml_to_lines():
    lines = page_xml_to_lines(PAGE_XML)
    assert [line.text for line in lines] == ["Omnibus sancte", "matris ecclesie"]
    assert lines[0].points[0] == [10.0, 20.0]


def test_alto_to_lines():
    lines = alto_to_lines(ALTO_XML)
    assert lines[0].text == "Omnibus sancte"
    # bbox polygon from HPOS/VPOS/WIDTH/HEIGHT
    assert lines[0].points[0] == [10.0, 20.0]
    assert lines[0].points[2] == [110.0, 60.0]


def test_lines_to_tei_with_graph_ids():
    lines = page_xml_to_lines(PAGE_XML)
    tei = lines_to_tei(lines, graph_ids=[55, None])
    assert '<seg type="line" corresp="#gid-55">Omnibus sancte</seg><lb/>' in tei
    assert '<seg type="line">matris ecclesie</seg><lb/>' in tei
    assert tei.startswith("<p>") and tei.endswith("</p>")


@pytest.mark.django_db
def test_import_htr_endpoint_creates_text_and_regions(management_client):
    image = ItemImageFactory()
    res = management_client.post(
        "/api/v1/manuscripts/management/image-texts/import-htr/",
        {"item_image": image.id, "format": "page", "type": "Transcription", "language": "la", "xml": PAGE_XML},
        format="json",
    )
    assert res.status_code == 201
    assert res.data["lines"] == 2
    assert res.data["regions"] == 2
    text = ImageText.objects.get(id=res.data["id"])
    assert text.status == ImageText.Status.DRAFT
    assert '<seg type="line" corresp="#gid-' in text.content
    # two TEXT graphs materialised on this image
    assert Graph.objects.filter(item_image=image, annotation_type="text").count() == 2


@pytest.mark.django_db
def test_import_htr_rejects_bad_xml(management_client):
    image = ItemImageFactory()
    res = management_client.post(
        "/api/v1/manuscripts/management/image-texts/import-htr/",
        {"item_image": image.id, "format": "page", "xml": "<not closed"},
        format="json",
    )
    assert res.status_code == 400


@pytest.mark.django_db
def test_import_htr_duplicate_kind_returns_409(management_client):
    image = ItemImageFactory()
    ImageText.objects.create(
        item_image=image,
        content="<p>existing</p>",
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.DRAFT,
        language="la",
    )
    res = management_client.post(
        "/api/v1/manuscripts/management/image-texts/import-htr/",
        {"item_image": image.id, "format": "page", "type": "Transcription", "xml": PAGE_XML},
        format="json",
    )
    assert res.status_code == 409


@pytest.mark.django_db
def test_import_htr_unknown_image_returns_404(management_client):
    res = management_client.post(
        "/api/v1/manuscripts/management/image-texts/import-htr/",
        {"item_image": 999999, "format": "page", "type": "Transcription", "xml": PAGE_XML},
        format="json",
    )
    assert res.status_code == 404


@pytest.mark.django_db
def test_import_htr_requires_superuser(authenticated_client):
    image = ItemImageFactory()
    res = authenticated_client.post(
        "/api/v1/manuscripts/management/image-texts/import-htr/",
        {"item_image": image.id, "format": "page", "xml": PAGE_XML},
        format="json",
    )
    assert res.status_code in (401, 403)

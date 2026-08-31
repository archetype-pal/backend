"""TEI-descriptions Phase 8.1 — `wrap_msdesc_document` + the `.tei` download.

Mirrors `test_tei_download.py` (the ImageText `tei/` action) for the msDesc
side. The publication gate is the load-bearing assertion: an anonymous download
must never carry an unpublished area.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from apps.manuscripts.models import MsDescArea
from apps.manuscripts.services.tei.document import wrap_msdesc_document
from apps.manuscripts.tests.factories import ItemPartFactory, MsDescAreaFactory

NS = "{http://www.tei-c.org/ns/1.0}"

MS_IDENTIFIER = "<msIdentifier><repository>NRS</repository><idno>RH1/2/3</idno></msIdentifier>"
MS_CONTENTS = "<msContents><summary>A royal charter.</summary></msContents>"
PHYS_DESC = '<physDesc><objectDesc form="sheet"><p>Single parchment sheet.</p></objectDesc></physDesc>'
HISTORY = "<history><origin><origDate notBefore='1150' notAfter='1200'>12th century</origDate></origin></history>"

# Malformed fragments the write path happily stores (MsDescAreaManagementSerializer
# does no well-formedness check, matching ImageText) but the export must not
# splice into the envelope verbatim.
UNCLOSED = "<physDesc><p>unclosed"
BREAKOUT = "<physDesc/></msDesc></sourceDesc></fileDesc></teiHeader><evil/>"
DOCTYPE_ENTITY = '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><physDesc><p>&e;</p></physDesc>'


def _parse(document: str) -> ET.Element:
    """Parse the document and hand back its `<TEI>` root (stdlib, as validate.py does)."""
    return ET.fromstring(document)


def _msdesc(root: ET.Element) -> ET.Element:
    found = root.find(f"{NS}teiHeader/{NS}fileDesc/{NS}sourceDesc/{NS}msDesc")
    assert found is not None, "msDesc must sit under teiHeader/fileDesc/sourceDesc"
    return found


def _area_order(root: ET.Element) -> list[str]:
    return [child.tag.removeprefix(NS) for child in _msdesc(root)]


class TestWrapMsDescDocument:
    def test_envelope_places_msdesc_in_the_header(self):
        document = wrap_msdesc_document({"physDesc": PHYS_DESC}, title="NRS RH1/2/3")

        assert document.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
        root = _parse(document)
        assert root.tag == f"{NS}TEI"
        title = root.find(f"{NS}teiHeader/{NS}fileDesc/{NS}titleStmt/{NS}title")
        assert title is not None and title.text == "NRS RH1/2/3"
        # The fragment rides in verbatim, under the root's default namespace.
        obj_desc = _msdesc(root).find(f"{NS}physDesc/{NS}objectDesc")
        assert obj_desc is not None and obj_desc.get("form") == "sheet"

    def test_emits_the_empty_text_body_stub(self):
        # A <TEI> root needs a resource after teiHeader, so a catalogue-only
        # record still carries <text><body><p/></body></text>.
        root = _parse(wrap_msdesc_document({"history": HISTORY}, title="t"))
        stub = root.find(f"{NS}text/{NS}body/{NS}p")
        assert stub is not None
        assert (stub.text or "") == ""
        assert len(root.find(f"{NS}text/{NS}body")) == 1

    def test_areas_are_emitted_in_msdesc_content_model_order(self):
        # Fed in the alphabetical order a queryset yields (MsDescArea.Meta
        # orders by `area`), which is NOT the TEI content-model order.
        document = wrap_msdesc_document(
            {
                "history": HISTORY,
                "msContents": MS_CONTENTS,
                "msIdentifier": MS_IDENTIFIER,
                "physDesc": PHYS_DESC,
            },
            title="t",
        )
        assert _area_order(_parse(document)) == ["msIdentifier", "msContents", "physDesc", "history"]

    def test_absent_and_blank_areas_are_skipped(self):
        document = wrap_msdesc_document(
            {"msIdentifier": MS_IDENTIFIER, "physDesc": "   ", "history": ""},
            title="t",
        )
        assert _area_order(_parse(document)) == ["msIdentifier"]

    def test_empty_mapping_yields_a_well_formed_empty_msdesc(self):
        # Documented contract: well-formed but not schema-valid (msIdentifier is
        # mandatory), which is why the view 404s instead of shipping this.
        root = _parse(wrap_msdesc_document({}, title="t"))
        assert list(_msdesc(root)) == []

    def test_title_and_source_note_are_escaped(self):
        document = wrap_msdesc_document(
            {"history": HISTORY},
            title="Charter <of> Malcolm & Co",
            source_note="Archetype ItemPart #7 <internal>",
        )
        root = _parse(document)  # would raise if the markup leaked through
        title = root.find(f"{NS}teiHeader/{NS}fileDesc/{NS}titleStmt/{NS}title")
        assert title is not None and title.text == "Charter <of> Malcolm & Co"
        # fileDesc admits exactly one publicationStmt; the note is a <p> in it.
        statements = root.findall(f"{NS}teiHeader/{NS}fileDesc/{NS}publicationStmt")
        assert len(statements) == 1
        assert [p.text for p in statements[0]][1] == "Archetype ItemPart #7 <internal>"

    def test_source_note_is_optional(self):
        root = _parse(wrap_msdesc_document({"history": HISTORY}, title="t"))
        statements = root.findall(f"{NS}teiHeader/{NS}fileDesc/{NS}publicationStmt")
        assert len(statements) == 1 and len(statements[0]) == 1


def _public_url(part_id: int) -> str:
    return f"/api/v1/manuscripts/item-parts/{part_id}/tei/"


def _management_url(part_id: int) -> str:
    return f"/api/v1/manuscripts/management/item-parts/{part_id}/tei/"


@pytest.mark.django_db
class TestPublicMsDescTeiDownload:
    def test_download_returns_attached_tei_document(self, api_client):
        area = MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC, content=PHYS_DESC, is_published=True)

        response = api_client.get(_public_url(area.item_part_id))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/tei+xml")
        assert response["Content-Disposition"] == f'attachment; filename="itempart-{area.item_part_id}-msdesc.tei"'
        body = response.content.decode()
        assert body.startswith('<?xml version="1.0"')
        root = _parse(body)
        assert _area_order(root) == ["physDesc"]
        title = root.find(f"{NS}teiHeader/{NS}fileDesc/{NS}titleStmt/{NS}title")
        assert title is not None and title.text == area.item_part.display_label()

    def test_unpublished_area_never_reaches_an_anonymous_download(self, api_client):
        published = MsDescAreaFactory(
            area=MsDescArea.Area.PHYS_DESC,
            content=PHYS_DESC,
            is_published=True,
        )
        MsDescAreaFactory(
            item_part=published.item_part,
            area=MsDescArea.Area.HISTORY,
            content=HISTORY,
            is_published=False,
        )

        body = api_client.get(_public_url(published.item_part_id)).content.decode()

        assert _area_order(_parse(body)) == ["physDesc"]
        assert "origDate" not in body
        assert "12th century" not in body

    def test_areas_are_reordered_out_of_queryset_order(self, api_client):
        part = ItemPartFactory()
        # Created (and stored) history-first; MsDescArea.Meta orders by `area`,
        # so the queryset also yields history before msIdentifier.
        MsDescAreaFactory(item_part=part, area=MsDescArea.Area.HISTORY, content=HISTORY, is_published=True)
        MsDescAreaFactory(
            item_part=part,
            area=MsDescArea.Area.MS_IDENTIFIER,
            content=MS_IDENTIFIER,
            is_published=True,
        )

        body = api_client.get(_public_url(part.pk)).content.decode()

        assert _area_order(_parse(body)) == ["msIdentifier", "history"]

    def test_404_when_nothing_is_published(self, api_client):
        area = MsDescAreaFactory(content=PHYS_DESC, is_published=False)
        assert api_client.get(_public_url(area.item_part_id)).status_code == 404

    def test_404_when_the_only_published_area_is_empty(self, api_client):
        area = MsDescAreaFactory(content="", is_published=True)
        assert api_client.get(_public_url(area.item_part_id)).status_code == 404

    def test_404_for_unknown_part(self, api_client):
        assert api_client.get(_public_url(999_999)).status_code == 404

    @pytest.mark.parametrize("bad", [UNCLOSED, BREAKOUT, DOCTYPE_ENTITY], ids=["unclosed", "breakout", "doctype"])
    def test_404_when_the_only_published_area_is_malformed(self, api_client, bad):
        # Better a missing resource than 200 + unparseable application/tei+xml.
        area = MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC, content=bad, is_published=True)
        assert api_client.get(_public_url(area.item_part_id)).status_code == 404

    @pytest.mark.parametrize("bad", [UNCLOSED, BREAKOUT, DOCTYPE_ENTITY], ids=["unclosed", "breakout", "doctype"])
    def test_malformed_area_is_skipped_and_the_rest_still_parses(self, api_client, bad):
        # One bad draft must not make a published record undownloadable — nor
        # let markup out of the fragment and into the envelope.
        good = MsDescAreaFactory(area=MsDescArea.Area.MS_IDENTIFIER, content=MS_IDENTIFIER, is_published=True)
        MsDescAreaFactory(
            item_part=good.item_part,
            area=MsDescArea.Area.PHYS_DESC,
            content=bad,
            is_published=True,
        )

        response = api_client.get(_public_url(good.item_part_id))

        assert response.status_code == 200
        body = response.content.decode()
        root = _parse(body)  # the whole point: it parses
        assert _area_order(root) == ["msIdentifier"]
        assert "<evil" not in body
        assert "DOCTYPE" not in body
        assert "unclosed" not in body

    def test_superuser_gets_the_same_published_only_document(self, management_client):
        # No staff branch on the public URL — the body must not vary by caller.
        published = MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC, content=PHYS_DESC, is_published=True)
        MsDescAreaFactory(
            item_part=published.item_part,
            area=MsDescArea.Area.HISTORY,
            content=HISTORY,
            is_published=False,
        )

        response = management_client.get(_public_url(published.item_part_id))

        assert response.status_code == 200
        assert _area_order(_parse(response.content.decode())) == ["physDesc"]


@pytest.mark.django_db
class TestManagementMsDescTeiDownload:
    def test_superuser_download_includes_unpublished_areas(self, management_client):
        published = MsDescAreaFactory(area=MsDescArea.Area.PHYS_DESC, content=PHYS_DESC, is_published=True)
        MsDescAreaFactory(
            item_part=published.item_part,
            area=MsDescArea.Area.HISTORY,
            content=HISTORY,
            is_published=False,
        )

        response = management_client.get(_management_url(published.item_part_id))

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/tei+xml")
        assert response["Content-Disposition"] == (
            f'attachment; filename="itempart-{published.item_part_id}-msdesc.tei"'
        )
        assert _area_order(_parse(response.content.decode())) == ["physDesc", "history"]

    def test_404_when_the_part_has_no_areas(self, management_client):
        part = ItemPartFactory()
        assert management_client.get(_management_url(part.pk)).status_code == 404

    def test_malformed_area_is_reported_not_skipped(self, management_client):
        # The editorial twin refuses rather than shipping a silently truncated
        # export: the cataloguer is the one who can fix it.
        good = MsDescAreaFactory(area=MsDescArea.Area.MS_IDENTIFIER, content=MS_IDENTIFIER, is_published=True)
        MsDescAreaFactory(
            item_part=good.item_part,
            area=MsDescArea.Area.PHYS_DESC,
            content=UNCLOSED,
            is_published=True,
        )

        response = management_client.get(_management_url(good.item_part_id))

        assert response.status_code == 422
        payload = response.json()
        assert list(payload["errors"]) == ["physDesc"]
        error = payload["errors"]["physDesc"][0]
        assert {"line", "col", "message"} <= set(error)
        assert "mismatched tag" in error["message"]

    def test_every_malformed_area_is_named(self, management_client):
        part = ItemPartFactory()
        MsDescAreaFactory(item_part=part, area=MsDescArea.Area.PHYS_DESC, content=BREAKOUT, is_published=True)
        MsDescAreaFactory(item_part=part, area=MsDescArea.Area.HISTORY, content=DOCTYPE_ENTITY, is_published=False)

        response = management_client.get(_management_url(part.pk))

        assert response.status_code == 422
        assert sorted(response.json()["errors"]) == ["history", "physDesc"]

    def test_anonymous_denied(self, api_client):
        area = MsDescAreaFactory(content=HISTORY, area=MsDescArea.Area.HISTORY, is_published=False)
        response = api_client.get(_management_url(area.item_part_id))
        assert response.status_code in (401, 403)
        assert "origDate" not in response.content.decode()

    def test_regular_user_denied(self, authenticated_client):
        area = MsDescAreaFactory(content=HISTORY, area=MsDescArea.Area.HISTORY, is_published=False)
        assert authenticated_client.get(_management_url(area.item_part_id)).status_code == 403


DESCRIPTION = (
    '<div xmlns="http://www.tei-c.org/ns/1.0" type="description">'
    '<p>Granted by <persName key="person_1" target="/scribes/1">William I</persName>'
    " to the abbey of <placeName>Melrose</placeName>.</p>"
    "</div>"
)


class TestLinkedDescriptionsInTheExport:
    """docs/tei.md §4.5 — a linked-prose description rides in `<text><body>`."""

    def test_description_lands_in_text_body_not_in_msdesc(self):
        # A <div> is a textstructure element; it is not a legal child of <msDesc>.
        document = wrap_msdesc_document(
            {"msIdentifier": MS_IDENTIFIER}, title="NRS RH1/2/3", descriptions=[DESCRIPTION]
        )
        root = _parse(document)

        body = root.find(f"{NS}text/{NS}body")
        assert body is not None
        assert [child.tag.removeprefix(NS) for child in body] == ["div"]
        assert body[0].get("type") == "description"
        # …and nothing description-shaped leaked into the header.
        assert _msdesc(root).find(f"{NS}div") is None

    def test_the_prose_survives_with_its_links(self):
        document = wrap_msdesc_document({"msIdentifier": MS_IDENTIFIER}, title="t", descriptions=[DESCRIPTION])
        root = _parse(document)
        pers = root.find(f"{NS}text/{NS}body/{NS}div/{NS}p/{NS}persName")
        assert pers is not None
        assert pers.get("target") == "/scribes/1"
        assert pers.text == "William I"

    def test_empty_stub_remains_when_there_are_no_descriptions(self):
        # A <TEI> root still needs a resource after the header.
        root = _parse(wrap_msdesc_document({"msIdentifier": MS_IDENTIFIER}, title="t"))
        body = root.find(f"{NS}text/{NS}body")
        assert [child.tag.removeprefix(NS) for child in body] == ["p"]

    def test_blank_descriptions_do_not_produce_an_empty_body(self):
        root = _parse(wrap_msdesc_document({"msIdentifier": MS_IDENTIFIER}, title="t", descriptions=["", "  "]))
        body = root.find(f"{NS}text/{NS}body")
        assert [child.tag.removeprefix(NS) for child in body] == ["p"]

    def test_several_descriptions_all_appear_in_order(self):
        second = DESCRIPTION.replace("William I", "Malcolm IV")
        root = _parse(
            wrap_msdesc_document({"msIdentifier": MS_IDENTIFIER}, title="t", descriptions=[DESCRIPTION, second])
        )
        divs = root.findall(f"{NS}text/{NS}body/{NS}div")
        assert len(divs) == 2
        assert divs[0].find(f"{NS}p/{NS}persName").text == "William I"
        assert divs[1].find(f"{NS}p/{NS}persName").text == "Malcolm IV"

    def test_document_stays_parseable(self):
        # The whole point of gating well-formedness upstream.
        document = wrap_msdesc_document({"msIdentifier": MS_IDENTIFIER}, title="t", descriptions=[DESCRIPTION])
        assert _parse(document) is not None

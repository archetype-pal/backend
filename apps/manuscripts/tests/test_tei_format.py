"""The formatter's contract: lay TEI out, never change what it says."""

import re
import xml.etree.ElementTree as ET

import pytest

from apps.manuscripts.services.tei import format_tei


def paragraph_text(content: str) -> list[str]:
    """Character data per top-level element, whitespace collapsed.

    Whitespace may move *between* paragraphs (a block boundary belongs to
    neither); inside one, the text must survive byte-for-byte once collapsed
    the way HTML collapses it.
    """
    root = ET.fromstring(f"<r>{content}</r>")
    return [re.sub(r"\s+", " ", "".join(node.itertext())).strip() for node in root]


CORPUS_SHAPES = [
    # A charter opening: nested segs, expansions, and a manuscript line break.
    '<p><seg type="address" corresp="#gid-1"><seg type="intitulatio">Alexander Dei Gratia Rex '
    "Scott<ex>orum</ex></seg> Omnibus Probis Hominibus Tocius Terre Sue Clericis Et Laycis "
    '<seg type="salutation">Salutem</seg> .</seg> <seg type="disposition">Sciatis '
    '<lb source="ms">|</lb> nos concessisse et hac carta nostra confirmasse illam quietam '
    "clamationem et abiurationem quam Patricius filius Comitis fecit pro se</seg></p>",
    # Elements written flush together — the case that must NOT gain a space.
    '<p><seg type="salutation">Salutem</seg><lb source="ms">|</lb> Noueritis me Concessisse et '
    "Hac presenti Carta mea Confirmasse deo et Ecclesie sancte Marie De Melros</p>",
    # A long unmarked translation: one 700-character run with no child elements.
    "<p>To all Christ's faithful who shall see or hear the present text, Alexander of Seton, "
    "knight, son of Sir Saer of Seton, greeting in the Lord. Let your whole community know "
    "[that I] have given, granted, and by this my present charter made firm, to God and to the "
    "church of St Mary at Melrose and the monks in that place serving God now and in the future.</p>",
    # Two paragraphs, flush.
    "<p>First paragraph here.</p><p>Second paragraph here.</p>",
    # Already laid out — reformatting must not drift.
    '<p>\n  <seg type="a">One</seg>\n  <seg type="b">Two</seg>\n</p>',
    # A person name nested in mixed content.
    '<p>Test<ex>ibus</ex> <persName type="name">Roger<ex>o</ex> Auenel</persName> . Ranulf<ex>o</ex> de Bonekyl .</p>',
]


@pytest.mark.parametrize("content", CORPUS_SHAPES)
def test_formatting_never_changes_the_text(content: str):
    assert paragraph_text(format_tei(content)) == paragraph_text(content)


@pytest.mark.parametrize("content", CORPUS_SHAPES)
def test_formatting_is_idempotent(content: str):
    once = format_tei(content)
    assert format_tei(once) == once


@pytest.mark.parametrize("content", CORPUS_SHAPES)
def test_formatting_preserves_every_tag(content: str):
    tags = lambda s: re.findall(r"<[^>]+>", s)  # noqa: E731
    assert tags(format_tei(content)) == tags(content)


def test_elements_written_flush_stay_flush():
    # `</seg><lb …>` with no whitespace between them: breaking the line here
    # would put a space into the transcription that the manuscript doesn't have.
    content = '<p><seg type="salutation">Salutem</seg><lb source="ms">|</lb> Noueritis</p>'
    assert "</seg><lb" in format_tei(content)


def test_long_line_is_wrapped():
    content = "<p>" + " ".join(["verbum"] * 80) + "</p>"
    formatted = format_tei(content)
    assert "\n" in formatted
    assert max(len(line) for line in formatted.splitlines()) <= 100


def test_line_breaks_start_at_manuscript_line_beginnings():
    content = '<p>Sciatis <lb source="ms">|</lb> nos concessisse <lb source="ms">|</lb> fecit</p>'
    lines = format_tei(content).splitlines()
    assert sum(line.lstrip().startswith("<lb") for line in lines) == 2


def test_malformed_content_is_returned_untouched():
    content = "<p><seg>unclosed</p>"
    assert format_tei(content) == content


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_content_is_returned_untouched(content):
    assert format_tei(content) == content


def test_bare_character_data_is_not_given_a_block_layout():
    # No wrapping <p>: there is no block boundary to hide a newline behind, so
    # the fragment flows as one run rather than gaining leading whitespace.
    content = "Loose text with <persName>a name</persName> in it."
    assert format_tei(content) == content


FORMAT_URL = "/api/v1/manuscripts/image-texts/format-tei/"

pytestmark = pytest.mark.django_db


def test_endpoint_returns_formatted_content(management_client):
    content = "<p>" + " ".join(["verbum"] * 40) + "</p>"
    res = management_client.post(FORMAT_URL, {"content": content}, format="json")
    assert res.status_code == 200
    assert "\n" in res.data["content"]
    assert paragraph_text(res.data["content"]) == paragraph_text(content)


def test_endpoint_rejects_malformed_markup(management_client):
    # Reflowing a fragment mid-repair would only lose the author's place, so the
    # caller is sent back to validate-tei instead.
    res = management_client.post(FORMAT_URL, {"content": "<p><seg>x</p>"}, format="json")
    assert res.status_code == 400
    assert len(res.data["errors"]) == 1


def test_endpoint_rejects_non_string_content(management_client):
    res = management_client.post(FORMAT_URL, {"content": 42}, format="json")
    assert res.status_code == 400


def test_endpoint_requires_auth(api_client):
    assert api_client.post(FORMAT_URL, {"content": "<p>x</p>"}, format="json").status_code == 401

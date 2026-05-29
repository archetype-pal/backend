"""Round-trip + mapping tests for the Phase H.2 data-dpt↔TEI converters.

Pure functions — no DB. The fixtures below cover every distinct `data-dpt`
construct found across the live 899-row corpus (verified 2026-05-27), plus
nesting, the `data-graph-id`↔`corresp` link, and passthrough of non-dpt
markup. The live-corpus round-trip (898/899, #646 excepted) is exercised
separately via the management shell during migration prep.
"""

import pytest

from apps.manuscripts.services.tei import data_dpt_to_tei, tei_to_data_dpt

# (data-dpt HTML, expected TEI) for each construct.
CONSTRUCTS: list[tuple[str, str]] = [
    (
        '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="address">x</span>',
        '<seg type="address">x</seg>',
    ),
    (
        '<span data-dpt="person" data-dpt-cat="chars" data-dpt-type="name">x</span>',
        '<persName type="name">x</persName>',
    ),
    (
        '<span data-dpt="person" data-dpt-cat="chars" data-dpt-type="title">x</span>',
        '<persName type="title">x</persName>',
    ),
    (
        '<span data-dpt="place" data-dpt-cat="chars" data-dpt-type="name">x</span>',
        '<placeName type="name">x</placeName>',
    ),
    ('<span data-dpt="ex" data-dpt-cat="chars">us</span>', "<ex>us</ex>"),
    ('<span data-dpt="supplied" data-dpt-cat="chars">x</span>', "<supplied>x</supplied>"),
    ('<span data-dpt="lb" data-dpt-src="ms">|</span>', '<lb source="ms">|</lb>'),
    ('<span data-dpt="lb" data-dpt-cat="sep">|</span>', '<lb type="sep">|</lb>'),
]


@pytest.mark.parametrize("dpt,tei", CONSTRUCTS)
def test_forward_maps_each_construct(dpt: str, tei: str) -> None:
    assert data_dpt_to_tei(dpt) == tei


@pytest.mark.parametrize("dpt,tei", CONSTRUCTS)
def test_round_trip_each_construct(dpt: str, tei: str) -> None:
    assert tei_to_data_dpt(data_dpt_to_tei(dpt)) == dpt


def test_graph_id_becomes_corresp_and_back() -> None:
    dpt = '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="salutation" data-graph-id="2824">salutem</span>'
    tei = data_dpt_to_tei(dpt)
    assert 'corresp="#gid-2824"' in tei
    assert "data-graph-id" not in tei
    assert tei_to_data_dpt(tei) == dpt


def test_multi_graph_id_round_trips() -> None:
    dpt = '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="address" data-graph-id="10,11">x</span>'
    tei = data_dpt_to_tei(dpt)
    assert 'corresp="#gid-10 #gid-11"' in tei
    assert tei_to_data_dpt(tei) == dpt


def test_nested_constructs_round_trip() -> None:
    dpt = (
        '<p><span data-dpt="clause" data-dpt-cat="words" data-dpt-type="intitulatio" data-graph-id="5507">'
        'Arnald<span data-dpt="ex" data-dpt-cat="chars">us</span> minister</span> . '
        '<span data-dpt="clause" data-dpt-cat="words" data-dpt-type="arenga">'
        'Ad <span data-dpt="lb" data-dpt-src="ms">|</span> spectat</span></p>'
    )
    assert tei_to_data_dpt(data_dpt_to_tei(dpt)) == dpt


def test_passthrough_non_dpt_markup() -> None:
    dpt = '<p>plain <em>emph</em> and <a href="/x">link</a> &amp; &nbsp;end</p>'
    # Tags pass through; XML-safe &amp; stays escaped; &nbsp; decodes to a char.
    assert data_dpt_to_tei(dpt) == '<p>plain <em>emph</em> and <a href="/x">link</a> &amp; \xa0end</p>'
    # Reverse leaves non-dpt markup untouched.
    plain = "<p>plain <em>emph</em></p>"
    assert tei_to_data_dpt(plain) == plain


def test_plain_span_without_dpt_is_untouched() -> None:
    dpt = '<span class="note">just a span</span>'
    assert data_dpt_to_tei(dpt) == dpt


def test_empty_content() -> None:
    assert data_dpt_to_tei("") == ""
    assert tei_to_data_dpt("") == ""


def test_self_closing_void_element_whitespace_preserved() -> None:
    # `<br />` (space before slash) must survive byte-for-byte both ways, else
    # the migration silently skips the row (regression: it became `<br/>`).
    for variant in ("<p>a<br />b</p>", "<p>a<br/>b</p>", "<p>a<br>b</p>"):
        assert data_dpt_to_tei(variant) == variant
        assert tei_to_data_dpt(data_dpt_to_tei(variant)) == variant


def test_unclosed_input_preserves_text_not_truncated() -> None:
    # Malformed/truncated input must not yield an empty string (silent loss);
    # the text is flushed even though the result stays unbalanced.
    out = data_dpt_to_tei('<p><seg type="address">Omnibus')
    assert "Omnibus" in out


def test_html_named_entities_become_xml_valid() -> None:
    # HTML named entities are undefined in XML, so the forward converter
    # decodes them to characters; XML-safe entities stay escaped.
    out = data_dpt_to_tei("<p>a&nbsp;b&aacute;c &amp; &lt;d&gt;</p>")
    assert out == "<p>a\xa0b\xe1c &amp; &lt;d&gt;</p>"
    assert "&nbsp;" not in out
    assert "&aacute;" not in out

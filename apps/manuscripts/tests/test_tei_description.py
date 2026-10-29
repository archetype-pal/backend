"""The server-side dual-format discriminator for historical-item descriptions.

Mirrors `frontend/lib/tei-description.test.ts`: the two implementations must
agree on what counts as a TEI description, because the frontend decides how a
row is edited and rendered while the backend decides whether it reaches the
`.tei` export.
"""

import pytest

from apps.manuscripts.services.tei.description import TEI_NS, is_tei_description, tei_description_body

PROSE = '<p>Granted by <persName key="person_1">William I</persName>.</p>'
WRAPPED = f'<div xmlns="{TEI_NS}" type="description">{PROSE}</div>'


@pytest.mark.parametrize(
    "content",
    [
        WRAPPED,
        f'<div type="description" xmlns="{TEI_NS}">{PROSE}</div>',  # attributes in the other order
        f"<div xmlns='{TEI_NS}'>{PROSE}</div>",  # single-quoted
        f'\n  <div\n   xmlns="{TEI_NS}"\n   type="description">\n{PROSE}\n</div>\n',  # whitespace
        f'<div xmlns="{TEI_NS}"></div>',
        f'<div xmlns="{TEI_NS}"/>',
        f'<div xmlns="{TEI_NS}"><div><p>x</p></div></div>',  # nested divs in the prose
    ],
)
def test_a_tei_namespaced_root_div_is_a_description(content):
    assert is_tei_description(content)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "<p><b>Melrose, Liber Sancte Marie</b>, no. 175.</p>",  # legacy catalogue HTML
        "<p>Witnesses are tagged <code>&lt;persName&gt;</code>.</p>",  # the false positive sniffing would give
        "<p>Witnessed by <persName>Walter</persName>.</p>",  # literal TEI markup inside legacy HTML
        '<div class="cat-entry"><p>no. 175</p></div>',  # a plain HTML div
        '<div xmlns="http://www.w3.org/1999/xhtml"><p>x</p></div>',  # another namespace
        f'<div xmlns="{TEI_NS}">{PROSE}</div><p>orphan</p>',  # the wrapper is not the root
        f'<p>lead</p><div xmlns="{TEI_NS}">{PROSE}</div>',
        f"<p>Encoded to {TEI_NS} P5.</p>",  # the namespace mentioned in text
    ],
)
def test_anything_else_is_legacy_html(content):
    assert not is_tei_description(content)


def test_body_is_the_wrapper_element_stripped_of_surrounding_whitespace():
    # Unlike the frontend, which hands the editor bare prose: an export needs
    # the <div>, which is what makes it a legal <text><body> resource.
    assert tei_description_body(f"\n {WRAPPED} \n") == WRAPPED
    assert tei_description_body("<p>no. 175</p>") is None

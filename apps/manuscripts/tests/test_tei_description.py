"""The server-side dual-format discriminator (docs/tei.md §4.5).

Mirrors `frontend/lib/tei-description.test.ts`. The two implementations must
agree on exactly one thing — what counts as a TEI description — because the
frontend decides how a row is edited and rendered while the backend decides
whether it reaches the `.tei` export.
"""

from apps.manuscripts.services.tei.description import (
    TEI_NS,
    is_tei_description,
    tei_description_body,
)

PROSE = '<p>Granted by <persName key="person_1">William I</persName>.</p>'
WRAPPED = f'<div xmlns="{TEI_NS}" type="description">{PROSE}</div>'


class TestAccepts:
    def test_canonical_wrapper(self):
        assert is_tei_description(WRAPPED)

    def test_attributes_in_the_other_order(self):
        assert is_tei_description(f'<div type="description" xmlns="{TEI_NS}">{PROSE}</div>')

    def test_single_quoted_values(self):
        assert is_tei_description(f"<div xmlns='{TEI_NS}'>{PROSE}</div>")

    def test_surrounding_and_internal_whitespace(self):
        assert is_tei_description(f'\n  <div\n   xmlns="{TEI_NS}"\n   type="description">\n{PROSE}\n</div>\n')

    def test_empty_wrapper_both_forms(self):
        assert is_tei_description(f'<div xmlns="{TEI_NS}"></div>')
        assert is_tei_description(f'<div xmlns="{TEI_NS}"/>')

    def test_nested_divs_in_the_prose(self):
        assert is_tei_description(f'<div xmlns="{TEI_NS}"><div><p>x</p></div></div>')


class TestRejects:
    def test_legacy_catalogue_html(self):
        assert not is_tei_description("<p><b>Melrose, Liber Sancte Marie</b>, no. 175.</p>")

    def test_legacy_html_quoting_tei_element_names(self):
        # The false-positive a sniffing discriminator would produce.
        quoting = "<p>Witnesses are tagged <code>&lt;persName&gt;</code>.</p>"
        assert not is_tei_description(quoting)

    def test_legacy_html_containing_literal_tei_markup(self):
        assert not is_tei_description("<p>Witnessed by <persName>Walter</persName>.</p>")

    def test_plain_html_div(self):
        assert not is_tei_description('<div class="cat-entry"><p>no. 175</p></div>')

    def test_other_namespace(self):
        assert not is_tei_description('<div xmlns="http://www.w3.org/1999/xhtml"><p>x</p></div>')

    def test_wrapper_that_is_not_the_root(self):
        assert not is_tei_description(f'<div xmlns="{TEI_NS}">{PROSE}</div><p>orphan</p>')

    def test_wrapper_starting_part_way_through(self):
        assert not is_tei_description(f'<p>lead</p><div xmlns="{TEI_NS}">{PROSE}</div>')

    def test_namespace_mentioned_in_text(self):
        assert not is_tei_description(f"<p>Encoded to {TEI_NS} P5.</p>")

    def test_empty_string(self):
        assert not is_tei_description("")


class TestBody:
    def test_returns_the_wrapper_element_not_the_bare_prose(self):
        # Unlike the frontend, which hands the editor bare prose: an export needs
        # the <div>, which is what makes it a legal <text><body> resource.
        assert tei_description_body(WRAPPED) == WRAPPED

    def test_returns_none_for_legacy_html(self):
        assert tei_description_body("<p>no. 175</p>") is None

    def test_strips_surrounding_whitespace(self):
        assert tei_description_body(f"\n {WRAPPED} \n") == WRAPPED


def test_agrees_with_the_frontend_fixtures():
    """The cases both implementations pin, kept together so drift is visible."""
    for accepted in (
        WRAPPED,
        f'<div xmlns="{TEI_NS}"/>',
        f'<div type="description" xmlns="{TEI_NS}">{PROSE}</div>',
    ):
        assert is_tei_description(accepted), accepted
    for rejected in (
        "",
        "<p>plain</p>",
        '<div class="x"><p>y</p></div>',
        f'<div xmlns="{TEI_NS}">{PROSE}</div><p>orphan</p>',
    ):
        assert not is_tei_description(rejected), rejected

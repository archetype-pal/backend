"""msDesc-derived facets on the item_parts document (TEI-descriptions 7.1).

Two layers:

* the pure extractor (`documents/msdesc_parser.py`) — one test per facet plus
  the degradation contract (malformed TEI must never raise);
* the builder wiring (`documents/item_parts.py`) — the publication gate, and
  the guarantee that `date`/`format` still come from relational columns rather
  than from re-parsed TEI.
"""

import pytest

from apps.search.documents.item_parts import build_item_part_document
from apps.search.documents.msdesc_parser import extract_msdesc_facets

# Realistic fragments, shaped like what the 2.x/3.1 editors write (see
# msdesc-minimal/msdesc-minimal-template.xml).
PHYS_DESC = (
    "<physDesc>"
    '<objectDesc form="codex">'
    '<supportDesc material="perg"><support><material>Parchment</material></support>'
    "<foliation>ii + 87 leaves.</foliation></supportDesc>"
    '<layoutDesc><layout columns="1" rulingMedium="leadpoint" topLine="above"><p>Long lines.</p></layout>'
    "</layoutDesc>"
    "</objectDesc>"
    '<handDesc hands="1"><handNote xml:id="h1" script="textualisNorthern" execution="formata">'
    "<p>A single practised hand.</p></handNote></handDesc>"
    '<decoDesc><summary>Modest decoration.</summary><decoNote type="flourInit"><p>Blue initials.</p>'
    "</decoNote></decoDesc>"
    "</physDesc>"
)

HISTORY = (
    "<history><origin>"
    '<origDate calendar="#Gregorian" notBefore="1400" notAfter="1500">15th century</origDate>'
    '<origPlace><country key="place_1">Scotland</country><settlement key="place_9">Kelso</settlement>'
    "</origPlace>"
    "</origin><provenance><p>Kelso Abbey.</p></provenance></history>"
)


# ── extractor ───────────────────────────────────────────────────────────


SEALS = (
    "<physDesc><sealDesc>"
    '<seal n="1" type="greatSeal" contemporary="true">'
    "<material>green wax</material><condition>fragment</condition>"
    "<p>Appended on a parchment tag.</p></seal>"
    '<seal n="2" type="counterseal"><material>green wax</material></seal>'
    "</sealDesc></physDesc>"
)


def test_extractor_pulls_seal_type_and_material():
    facets = extract_msdesc_facets([SEALS])

    assert facets == {
        "seal_type": ["greatSeal", "counterseal"],
        # De-duplicated: both seals are green wax.
        "seal_material": ["green wax"],
    }


def test_seal_material_does_not_leak_into_the_support_material_facet():
    # supportDesc/@material feeds `material`; a <material> *element* elsewhere is
    # free text about something else entirely and must not merge into it.
    facets = extract_msdesc_facets([PHYS_DESC, SEALS])

    assert facets["material"] == ["perg"]
    assert facets["seal_material"] == ["green wax"]


def test_support_material_element_is_not_a_seal_material():
    facets = extract_msdesc_facets(
        [
            "<physDesc><objectDesc><supportDesc><support>"
            "<material>Parchment</material></support></supportDesc></objectDesc></physDesc>"
        ]
    )

    assert "seal_material" not in facets


def test_extractor_pulls_the_four_new_facets():
    facets = extract_msdesc_facets([PHYS_DESC, HISTORY])

    assert facets == {
        "material": ["perg"],
        "script": ["textualisNorthern"],
        "deco_type": ["flourInit"],
        # settlement beats country: one origPlace contributes one value.
        "origin_place": ["Kelso"],
    }


def test_extractor_emits_nothing_for_facets_the_tei_does_not_carry():
    facets = extract_msdesc_facets(["<physDesc><additions><p>Marginalia.</p></additions></physDesc>"])

    assert facets == {}


def test_extractor_is_multi_valued_and_deduplicates_in_document_order():
    fragment = (
        "<physDesc>"
        '<handDesc hands="3">'
        '<handNote script="protogothic"><p>Hand A.</p></handNote>'
        '<handNote script="cursiva"><p>Hand B.</p></handNote>'
        '<handNote script="protogothic"><p>Hand C, same script as A.</p></handNote>'
        "</handDesc>"
        "<decoDesc>"
        '<decoNote type="initial"><p>Initials.</p></decoNote>'
        '<decoNote type="rubrication"><p>Rubrics.</p></decoNote>'
        '<decoNote type="initial"><p>More initials.</p></decoNote>'
        "</decoDesc>"
        "</physDesc>"
    )

    facets = extract_msdesc_facets([fragment])

    assert facets["script"] == ["protogothic", "cursiva"]
    assert facets["deco_type"] == ["initial", "rubrication"]


def test_extractor_deduplicates_across_fragments():
    other = '<physDesc><handDesc><handNote script="textualisNorthern"><p>Same.</p></handNote></handDesc></physDesc>'

    facets = extract_msdesc_facets([PHYS_DESC, other])

    assert facets["script"] == ["textualisNorthern"]


def test_extractor_reads_origin_place_through_markup_and_falls_back_to_less_specific_children():
    with_ref = (
        "<history><origin><origPlace>"
        '<settlement key="place_9">Kelso <ref target="/manuscripts/5">(see MS 5)</ref></settlement>'
        "</origPlace></origin></history>"
    )
    country_only = (
        '<history><origin><origPlace><country key="place_1">Scotland</country></origPlace></origin></history>'
    )
    bare_text = "<history><origin><origPlace>Dunfermline</origPlace></origin></history>"

    facets = extract_msdesc_facets([with_ref, country_only, bare_text])

    assert facets["origin_place"] == ["Kelso (see MS 5)", "Scotland", "Dunfermline"]


def test_extractor_ignores_orig_place_authored_outside_an_origin():
    """`origPlace` is a phrase leaf: the rich editor can drop it into any prose.

    Only the one inside ``origin`` is a place of *origin* — a provenance mention
    names where the manuscript later travelled, and must not become a facet.
    """
    fragment = (
        "<history>"
        "<origin><origPlace><settlement>Kelso</settlement></origPlace></origin>"
        "<provenance><p>Recorded at <origPlace>Melrose</origPlace> by 1220.</p></provenance>"
        "</history>"
    )

    assert extract_msdesc_facets([fragment])["origin_place"] == ["Kelso"]


def test_extractor_reads_orig_place_nested_in_origin_prose():
    """Scoping is by ancestor, not by direct parent — `<origin><p>…` still counts."""
    fragment = "<history><origin><p>Written at <origPlace>Arbroath</origPlace>.</p></origin></history>"

    assert extract_msdesc_facets([fragment])["origin_place"] == ["Arbroath"]


def test_extraction_is_area_agnostic_by_design():
    """Documented contract: fragments are scanned whole, not dispatched on `area`.

    A construct authored in an unexpected area still faces (which is what keeps
    a mislabelled ``area`` column from silently zeroing a facet). Asserted so the
    module docstring's claim can't drift from the behaviour.
    """
    misfiled = '<msContents><msItem><handNote script="uncial"/></msItem></msContents>'

    assert extract_msdesc_facets([misfiled]) == {"script": ["uncial"]}


def test_extractor_canonicalises_vocabulary_case_but_passes_unknown_values_through():
    fragment = (
        "<physDesc>"
        '<objectDesc form="codex"><supportDesc material="PERG"/></objectDesc>'
        '<handDesc><handNote script="charterHandNotInTheOdd"><p>Local term.</p></handNote></handDesc>'
        "</physDesc>"
    )

    facets = extract_msdesc_facets([fragment])

    assert facets["material"] == ["perg"]
    assert facets["script"] == ["charterHandNotInTheOdd"]


def test_extractor_handles_namespaced_fragments_and_padded_attribute_values():
    fragment = (
        '<physDesc xmlns="http://www.tei-c.org/ns/1.0">'
        '<objectDesc form="codex"><supportDesc material="  perg  "/></objectDesc>'
        "</physDesc>"
    )

    assert extract_msdesc_facets([fragment]) == {"material": ["perg"]}


@pytest.mark.parametrize(
    "fragment",
    [
        "",
        "   ",
        "<physDesc><supportDesc material='perg'>",  # unclosed
        "<physDesc><handNote script=></physDesc>",  # broken attribute
        "<physDesc>&notAnEntity;</physDesc>",
        "not xml at all",
        '<physDesc><supportDesc material=""/><handNote script="  "/><decoNote type=""/></physDesc>',
        "<history><origin><origPlace><settlement/></origPlace></origin></history>",
        None,  # a caller handing over a null content column
    ],
)
def test_extractor_never_raises_and_yields_nothing_for_unusable_fragments(fragment):
    assert extract_msdesc_facets([fragment]) == {}


# ── builder wiring ──────────────────────────────────────────────────────


def _part_with_areas(*areas):
    """An ItemPart with the given ``(area, content, is_published)`` msDesc rows."""
    from apps.manuscripts.tests.factories import ItemPartFactory, MsDescAreaFactory

    part = ItemPartFactory()
    for area, content, is_published in areas:
        MsDescAreaFactory(item_part=part, area=area, content=content, is_published=is_published)
    return part


@pytest.mark.django_db
def test_item_part_document_carries_published_msdesc_facets():
    from apps.manuscripts.models import MsDescArea

    part = _part_with_areas(
        (MsDescArea.Area.PHYS_DESC, PHYS_DESC, True),
        (MsDescArea.Area.HISTORY, HISTORY, True),
    )

    doc = build_item_part_document(part)

    assert doc["material"] == ["perg"]
    assert doc["script"] == ["textualisNorthern"]
    assert doc["deco_type"] == ["flourInit"]
    assert doc["origin_place"] == ["Kelso"]


@pytest.mark.django_db
def test_unpublished_msdesc_areas_contribute_no_facets():
    """Non-negotiable: the public facet rail is anonymous-facing."""
    from apps.manuscripts.models import MsDescArea

    part = _part_with_areas(
        (MsDescArea.Area.PHYS_DESC, PHYS_DESC, False),
        (MsDescArea.Area.HISTORY, HISTORY, False),
    )

    doc = build_item_part_document(part)

    for key in ("material", "script", "deco_type", "origin_place"):
        assert key not in doc


@pytest.mark.django_db
def test_only_the_published_area_of_a_mixed_pair_contributes():
    from apps.manuscripts.models import MsDescArea

    part = _part_with_areas(
        (MsDescArea.Area.PHYS_DESC, PHYS_DESC, False),
        (MsDescArea.Area.HISTORY, HISTORY, True),
    )

    doc = build_item_part_document(part)

    assert doc["origin_place"] == ["Kelso"]
    assert "material" not in doc
    assert "script" not in doc
    assert "deco_type" not in doc


@pytest.mark.django_db
def test_item_part_without_msdesc_areas_is_unchanged():
    from apps.manuscripts.tests.factories import ItemPartFactory

    doc = build_item_part_document(ItemPartFactory())

    assert not {"material", "script", "deco_type", "origin_place"} & set(doc)


@pytest.mark.django_db
def test_malformed_published_fragment_does_not_break_the_document():
    from apps.manuscripts.models import MsDescArea

    part = _part_with_areas((MsDescArea.Area.PHYS_DESC, "<physDesc><supportDesc material='perg'>", True))

    doc = build_item_part_document(part)

    assert doc["id"] == part.id
    assert "material" not in doc


@pytest.mark.django_db
def test_registry_prefetch_keeps_the_builder_query_free(django_assert_num_queries):
    """Without ``msdesc_areas`` in the prefetch spec this costs one query per row."""
    from apps.manuscripts.models import ItemPart, MsDescArea
    from apps.search.registry import INDEX_REGISTRY
    from apps.search.types import IndexType

    _part_with_areas(
        (MsDescArea.Area.PHYS_DESC, PHYS_DESC, True),
        (MsDescArea.Area.HISTORY, HISTORY, True),
    )
    registration = INDEX_REGISTRY[IndexType.ITEM_PARTS]
    assert "msdesc_areas" in registration.prefetch_related

    queryset = ItemPart.objects.select_related(*registration.select_related)
    parts = list(queryset.prefetch_related(*registration.prefetch_related))
    with django_assert_num_queries(0):
        for part in parts:
            build_item_part_document(part)


@pytest.mark.django_db
def test_date_and_format_still_come_from_relational_columns_not_tei():
    """7.1 forbids TEI-derived date/format duplicates — origDate must be inert."""
    from apps.manuscripts.models import MsDescArea

    part = _part_with_areas((MsDescArea.Area.HISTORY, HISTORY, True))

    doc = build_item_part_document(part)

    # DateFactory values, not the fragment's notBefore/notAfter="1400"/"1500".
    assert doc["date"] == part.historical_item.date.date
    assert doc["date_min"] == part.historical_item.date.min_weight
    assert doc["date_max"] == part.historical_item.date.max_weight
    assert doc["format"] == part.historical_item.format.name
    assert "1400" not in {str(value) for value in doc.values()}
    # No origin-date facet key of any spelling was introduced.
    assert not {key for key in doc if "orig" in key and "date" in key.lower()}

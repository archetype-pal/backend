"""The text-derived builders (texts, clauses, people, places): region links and their coordinates."""

import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.search.documents.clauses import build_clause_documents
from apps.search.documents.dpt_parser import extract_all
from apps.search.documents.people import build_person_documents
from apps.search.documents.places import build_place_documents
from apps.search.documents.texts import build_text_document

pytestmark = pytest.mark.django_db

POLYGON = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}


def _region(image, annotation_type="text") -> Graph:
    graph: Graph = Graph.objects.create(item_image=image, annotation=POLYGON, annotation_type=annotation_type)
    return graph


def _text(image, content: str, **fields) -> ImageText:
    fields = {"type": ImageText.Type.TRANSCRIPTION, "status": ImageText.Status.LIVE, **fields}
    return ImageTextFactory(item_image=image, content=content, **fields)


@pytest.mark.parametrize(
    "content",
    [
        # Legacy data-dpt and TEI yield the same extraction.
        '<span data-dpt="clause" data-dpt-type="address" data-graph-id="12">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name" data-graph-id="88,99">John</span>'
        '<span data-dpt="place" data-dpt-type="region">Paris</span>',
        '<p><seg type="address" corresp="#gid-12">Alpha</seg>'
        '<persName type="name" corresp="#gid-88 #gid-99">John</persName>'
        '<placeName type="region">Paris</placeName></p>',
    ],
)
def test_extract_all_reads_links_from_either_markup(content):
    extracted = extract_all(content)

    assert [(c["type"], c["annotation_id"]) for c in extracted["clauses"]] == [("address", 12)]
    assert [(p["name"], p["annotation_id"]) for p in extracted["people"]] == [("John", 88)]
    assert [(p["name"], p["annotation_id"]) for p in extracted["places"]] == [("Paris", None)]


def test_builders_carry_the_linked_region_or_null():
    image = ItemImageFactory()
    clause_region, place_region = _region(image), _region(image)
    text = _text(
        image,
        f'<p><seg type="address" corresp="#gid-{clause_region.id}">Alpha</seg>'
        '<persName type="name">John</persName>'
        f'<placeName type="region" corresp="#gid-{place_region.id}">Paris</placeName></p>',
    )

    [clause] = build_clause_documents(text)
    [person] = build_person_documents(text)
    [place] = build_place_documents(text)
    whole = build_text_document(text)

    assert (clause["id"], clause["annotation_id"]) == (f"{text.id}_0", clause_region.id)
    assert clause["annotation_coordinates"]
    assert (person["annotation_id"], person["annotation_coordinates"]) == (None, None)
    assert (place["annotation_id"], bool(place["annotation_coordinates"])) == (place_region.id, True)
    # The whole-text document takes the first linked region; John is still a person facet.
    assert whole["annotation_id"] == clause_region.id
    assert whole["annotation_coordinates"]
    assert "John" in whole["people"]


def test_a_text_with_no_links_still_has_its_documents():
    # An unlinked clause still belongs in the index: its card falls back to the
    # page scan. Dropping it emptied the category on a corpus with no links.
    text = _text(ItemImageFactory(), '<p><seg type="address">Alpha</seg></p>')

    [clause] = build_clause_documents(text)
    whole = build_text_document(text)

    assert (clause["clause_type"], clause["content"], clause["annotation_id"]) == ("address", "Alpha", None)
    assert clause["annotation_coordinates"] is None
    assert (whole["annotation_id"], whole["annotation_coordinates"]) == (None, None)


def test_clauses_borrow_regions_from_the_images_other_text_by_type_and_ordinal():
    image = ItemImageFactory()
    first, second = _region(image), _region(image)
    transcription = _text(
        image,
        '<p><seg type="witnesses">One</seg><seg type="witnesses">Two</seg><seg type="dating">Three</seg></p>',
    )
    _text(
        image,
        f'<p><seg type="witnesses" corresp="#gid-{first.id}">Un</seg>'
        f'<seg type="witnesses" corresp="#gid-{second.id}">Deux</seg></p>',
        type=ImageText.Type.TRANSLATION,
    )

    docs = build_clause_documents(transcription)

    # Two clauses of the same type must not both take the first donor; the dating has no donor.
    assert [(d["clause_type"], d["annotation_id"]) for d in docs] == [
        ("witnesses", first.id),
        ("witnesses", second.id),
        ("dating", None),
    ]
    assert docs[0]["annotation_coordinates"]


def test_text_derived_documents_leave_out_editorial_region_coordinates():
    # These indexes are public; editorial annotations are for signed-in users only.
    image = ItemImageFactory()
    editorial, region = _region(image, "editorial"), _region(image)
    text = _text(
        image,
        f'<p><seg type="address" corresp="#gid-{editorial.id}">Alpha</seg>'
        f'<seg type="dating" corresp="#gid-{region.id}">Beta</seg>'
        f'<persName type="name" corresp="#gid-{editorial.id}">John</persName>'
        f'<placeName type="name" corresp="#gid-{editorial.id}">Paris</placeName></p>',
    )

    clauses = {d["clause_type"]: d for d in build_clause_documents(text)}
    assert clauses["address"]["annotation_coordinates"] is None
    assert clauses["dating"]["annotation_coordinates"]
    assert [d["annotation_coordinates"] for d in build_person_documents(text)] == [None]
    assert [d["annotation_coordinates"] for d in build_place_documents(text)] == [None]
    assert build_text_document(text)["annotation_coordinates"] is None

from types import SimpleNamespace

import pytest

from apps.annotations.models import Graph
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ItemImageFactory
import apps.search.documents.clauses as clauses_docs
from apps.search.documents.dpt_parser import extract_all
import apps.search.documents.people as people_docs
import apps.search.documents.places as places_docs
import apps.search.documents.texts as texts_docs
import apps.search.documents.utils as utils_docs


def _fake_image_text(content: str):
    repository = SimpleNamespace(name="Repo", place="City")
    current_item = SimpleNamespace(repository=repository, shelfmark="Shelf")
    historical_item = SimpleNamespace(type="charter", date=None, get_catalogue_numbers_display=lambda: "Cat 1")
    item_part = SimpleNamespace(id=10, current_item=current_item, historical_item=historical_item)
    image_field = SimpleNamespace(iiif=SimpleNamespace(info="iiif://thumb"))
    item_image = SimpleNamespace(id=20, item_part=item_part, locus="fol.1r", image=image_field)
    return SimpleNamespace(
        id=99,
        content=content,
        type="Transcription",
        status="Draft",
        language="la",
        item_image=item_image,
    )


def _patch_graph_lookup(monkeypatch, filter_graphs):
    """Stand in for the Graph lookup annotation_coordinates_map makes."""
    monkeypatch.setattr(
        utils_docs.Graph, "objects", SimpleNamespace(exclude=lambda **_: SimpleNamespace(filter=filter_graphs))
    )


def test_extract_all_parses_annotation_ids_from_data_dpt_spans():
    html = (
        '<span data-dpt="clause" data-dpt-type="address" data-graph-id="12">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name" data-graph-id="88,99">John</span>'
        '<span data-dpt="place" data-dpt-type="region">Paris</span>'
    )
    extracted = extract_all(html)

    assert extracted["clauses"][0]["annotation_id"] == 12
    assert extracted["people"][0]["annotation_id"] == 88
    assert extracted["places"][0]["annotation_id"] is None


def test_extract_all_parses_tei_content():
    # TEI is converted internally, so it yields the same output as data-dpt.
    tei = (
        '<p><seg type="address" corresp="#gid-12">Alpha</seg>'
        '<persName type="name" corresp="#gid-88">John</persName>'
        '<placeName type="name">Paris</placeName></p>'
    )
    extracted = extract_all(tei)

    assert extracted["clauses"][0]["type"] == "address"
    assert extracted["clauses"][0]["annotation_id"] == 12
    assert extracted["people"][0]["name"] == "John"
    assert extracted["people"][0]["annotation_id"] == 88
    assert extracted["places"][0]["name"] == "Paris"


def test_clause_people_place_builders_emit_annotation_id_or_null(monkeypatch):
    obj = _fake_image_text(
        '<span data-dpt="clause" data-dpt-type="address" data-graph-id="100">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name">John</span>'
        '<span data-dpt="place" data-dpt-type="region" data-graph-id="77">Paris</span>'
    )

    # All three builders resolve coordinates through annotation_coordinates_map,
    # so Graph is patched there once, id-aware.
    graphs_by_id = {
        100: SimpleNamespace(id=100, annotation={"type": "Feature", "geometry": {"type": "Polygon"}}),
        77: SimpleNamespace(id=77, annotation={"type": "Feature", "geometry": {"type": "Polygon"}}),
    }
    _patch_graph_lookup(
        monkeypatch,
        lambda **kwargs: [g for gid, g in graphs_by_id.items() if gid in kwargs.get("id__in", ())],
    )

    clause_docs = clauses_docs.build_clause_documents(obj)
    people = people_docs.build_person_documents(obj)
    place_docs = places_docs.build_place_documents(obj)

    assert clause_docs[0]["annotation_id"] == 100
    assert "annotation_coordinates" in clause_docs[0]
    assert people[0]["annotation_id"] is None
    assert "annotation_coordinates" in people[0]
    assert place_docs[0]["annotation_id"] == 77
    assert "annotation_coordinates" in place_docs[0]


def test_text_builder_sets_annotation_id_when_any_dpt_annotation_exists(monkeypatch):
    obj = _fake_image_text(
        '<span data-dpt="clause" data-dpt-type="address" data-graph-id="42">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name">John</span>'
    )

    graph = SimpleNamespace(annotation={"type": "Feature", "geometry": {"type": "Polygon"}})
    monkeypatch.setattr(
        texts_docs.Graph,
        "objects",
        SimpleNamespace(exclude=lambda **_: SimpleNamespace(only=lambda *_: SimpleNamespace(get=lambda **__: graph))),
    )

    doc = texts_docs.build_text_document(obj)

    assert doc["annotation_id"] == 42
    assert "annotation_coordinates" in doc
    assert "John" in doc["people"]


def test_text_builder_sets_annotation_id_to_null_when_missing():
    obj = _fake_image_text('<span data-dpt="person" data-dpt-type="name">John</span>')

    doc = texts_docs.build_text_document(obj)

    assert "annotation_id" in doc
    assert doc["annotation_id"] is None
    assert "annotation_coordinates" in doc
    assert doc["annotation_coordinates"] is None


def _with_sibling(obj, sibling_content: str, sibling_id: int = 98):
    """Attach a second ImageText to obj's item_image, as the ORM prefetch does."""
    sibling = SimpleNamespace(id=sibling_id, content=sibling_content, type="Translation")
    obj.item_image.texts = SimpleNamespace(all=lambda: [obj, sibling])
    return obj


def test_clause_builder_indexes_clauses_with_no_linked_region():
    # An unlinked clause still belongs in the index: its card falls back to the
    # page scan. Dropping it emptied the category on a corpus with no links.
    obj = _fake_image_text('<span data-dpt="clause" data-dpt-type="address">Alpha</span>')

    docs = clauses_docs.build_clause_documents(obj)

    assert [(d["clause_type"], d["content"], d["annotation_id"]) for d in docs] == [("address", "Alpha", None)]
    assert docs[0]["annotation_coordinates"] is None


def test_clause_builder_borrows_annotation_from_the_images_other_text(monkeypatch):
    obj = _with_sibling(
        _fake_image_text(
            '<span data-dpt="clause" data-dpt-type="address">Alpha</span>'
            '<span data-dpt="clause" data-dpt-type="dating">Beta</span>'
        ),
        '<span data-dpt="clause" data-dpt-type="address" data-graph-id="55">Alpha translated</span>',
    )
    _patch_graph_lookup(
        monkeypatch,
        lambda **kwargs: [SimpleNamespace(id=55, annotation={"type": "Feature"})] if 55 in kwargs["id__in"] else [],
    )

    docs = clauses_docs.build_clause_documents(obj)

    # The address borrows the translation's region; the dating has none.
    assert [(d["id"], d["clause_type"], d["annotation_id"]) for d in docs] == [
        ("99_0", "address", 55),
        ("99_1", "dating", None),
    ]
    assert docs[0]["annotation_coordinates"]


def test_clause_builder_matches_siblings_by_type_and_ordinal(monkeypatch):
    # Two clauses of the same type must not both take the first donor.
    obj = _with_sibling(
        _fake_image_text(
            '<span data-dpt="clause" data-dpt-type="witnesses">One</span>'
            '<span data-dpt="clause" data-dpt-type="witnesses">Two</span>'
        ),
        '<span data-dpt="clause" data-dpt-type="witnesses" data-graph-id="11">One</span>'
        '<span data-dpt="clause" data-dpt-type="witnesses" data-graph-id="22">Two</span>',
    )
    _patch_graph_lookup(
        monkeypatch,
        lambda **kwargs: [SimpleNamespace(id=gid, annotation={"type": "Feature"}) for gid in kwargs["id__in"]],
    )

    docs = clauses_docs.build_clause_documents(obj)

    assert [d["annotation_id"] for d in docs] == [11, 22]


@pytest.mark.django_db
def test_text_derived_documents_leave_out_editorial_region_coordinates():
    # These indexes are public; editorial annotations are for signed-in users only.
    polygon = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}}
    image = ItemImageFactory()
    editorial = Graph.objects.create(item_image=image, annotation=polygon, annotation_type="editorial")
    region = Graph.objects.create(item_image=image, annotation=polygon, annotation_type="text")
    text = ImageText.objects.create(
        item_image=image,
        content=f'<p><seg type="address" corresp="#gid-{editorial.id}">Alpha</seg>'
        f'<seg type="dating" corresp="#gid-{region.id}">Beta</seg>'
        f'<persName type="name" corresp="#gid-{editorial.id}">John</persName>'
        f'<placeName type="name" corresp="#gid-{editorial.id}">Paris</placeName></p>',
        type=ImageText.Type.TRANSCRIPTION,
        status=ImageText.Status.LIVE,
        language="la",
    )

    clauses = {d["clause_type"]: d for d in clauses_docs.build_clause_documents(text)}
    assert clauses["address"]["annotation_coordinates"] is None
    assert clauses["dating"]["annotation_coordinates"]
    assert [d["annotation_coordinates"] for d in people_docs.build_person_documents(text)] == [None]
    assert [d["annotation_coordinates"] for d in places_docs.build_place_documents(text)] == [None]
    assert texts_docs.build_text_document(text)["annotation_coordinates"] is None

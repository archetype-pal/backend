from types import SimpleNamespace

import apps.search.documents.clauses as clauses_docs
from apps.search.documents.dpt_parser import extract_all
import apps.search.documents.people as people_docs
import apps.search.documents.places as places_docs
import apps.search.documents.texts as texts_docs


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


def test_extract_all_parses_annotation_ids_from_data_dpt_spans():
    html = (
        '<span data-dpt="clause" data-dpt-type="address" data-annotation-id="12">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name" data-annotation-id="88,99">John</span>'
        '<span data-dpt="place" data-dpt-type="region">Paris</span>'
    )
    extracted = extract_all(html)

    assert extracted["clauses"][0]["annotation_id"] == 12
    assert extracted["people"][0]["annotation_id"] == 88
    assert extracted["places"][0]["annotation_id"] is None


def test_clause_people_place_builders_emit_annotation_id_or_null():
    obj = _fake_image_text(
        '<span data-dpt="clause" data-dpt-type="address" data-annotation-id="100">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name">John</span>'
        '<span data-dpt="place" data-dpt-type="region" data-annotation-id="77">Paris</span>'
    )

    clauses_graph_qs = [SimpleNamespace(id=100, annotation={"type": "Feature", "geometry": {"type": "Polygon"}})]
    places_graph_qs = [SimpleNamespace(id=77, annotation={"type": "Feature", "geometry": {"type": "Polygon"}})]

    clauses_docs.Graph.objects = SimpleNamespace(filter=lambda **_: clauses_graph_qs)
    people_docs.Graph.objects = SimpleNamespace(filter=lambda **_: [])
    places_docs.Graph.objects = SimpleNamespace(filter=lambda **_: places_graph_qs)

    clause_docs = clauses_docs.build_clause_documents(obj)
    people = people_docs.build_person_documents(obj)
    place_docs = places_docs.build_place_documents(obj)

    assert clause_docs[0]["annotation_id"] == 100
    assert "annotation_coordinates" in clause_docs[0]
    assert people[0]["annotation_id"] is None
    assert "annotation_coordinates" in people[0]
    assert place_docs[0]["annotation_id"] == 77
    assert "annotation_coordinates" in place_docs[0]


def test_text_builder_sets_annotation_id_when_any_dpt_annotation_exists():
    obj = _fake_image_text(
        '<span data-dpt="clause" data-dpt-type="address" data-annotation-id="42">Alpha</span>'
        '<span data-dpt="person" data-dpt-type="name">John</span>'
    )

    texts_docs.Graph.objects = SimpleNamespace(
        only=lambda *_: SimpleNamespace(
            get=lambda **__: SimpleNamespace(annotation={"type": "Feature", "geometry": {"type": "Polygon"}})
        )
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

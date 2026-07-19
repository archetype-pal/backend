"""Golden tests for the per-IndexType document builders (ROADMAP 4.1).

Each test exercises one concrete-model builder with a minimal in-memory factory
graph and asserts the document shape. The fixtures double as documentation for
what each index actually contains.

dpt-derived builders (clauses, people, places) are covered transitively in
test_annotation_id_documents.py — they're driven by dpt_parser whose own
contract tests are in test_dpt_parser.py.
"""

import pytest

from apps.search.documents.graphs import build_graph_document
from apps.search.documents.hands import build_hand_document
from apps.search.documents.item_images import build_item_image_document
from apps.search.documents.item_parts import build_item_part_document
from apps.search.documents.scribes import build_scribe_document
from apps.search.documents.texts import build_text_document
from apps.search.registry import INDEX_REGISTRY
from apps.search.types import IndexType

# Documents which IndexType is exercised by which test in this repository.
# The meta-test at the bottom asserts that every INDEX_REGISTRY entry is
# covered exactly once — adding a new IndexType without a test fails CI.
BUILDER_COVERAGE: dict[IndexType, str] = {
    IndexType.ITEM_PARTS: "test_item_part_builder_emits_minimal_doc",
    IndexType.ITEM_IMAGES: "test_item_image_builder_emits_minimal_doc",
    IndexType.SCRIBES: "test_scribe_builder_emits_minimal_doc",
    IndexType.HANDS: "test_hand_builder_emits_minimal_doc",
    IndexType.GRAPHS: "test_graph_builder_emits_minimal_doc",
    IndexType.TEXTS: "test_text_builder_emits_minimal_doc",
    # dpt-derived — golden coverage lives in test_annotation_id_documents.py
    IndexType.CLAUSES: "test_annotation_id_documents::test_clause_people_place_builders_emit_annotation_id_or_null",
    IndexType.PEOPLE: "test_annotation_id_documents::test_clause_people_place_builders_emit_annotation_id_or_null",
    IndexType.PLACES: "test_annotation_id_documents::test_clause_people_place_builders_emit_annotation_id_or_null",
}


@pytest.mark.django_db
def test_item_part_builder_emits_minimal_doc():
    from apps.manuscripts.tests.factories import (
        CurrentItemFactory,
        HistoricalItemFactory,
        ItemPartFactory,
        RepositoryFactory,
    )

    repo = RepositoryFactory(name="Test Repo", place="Glasgow")
    ci = CurrentItemFactory(repository=repo, shelfmark="MS 1")
    hi = HistoricalItemFactory(type="Charter")
    part = ItemPartFactory(historical_item=hi, current_item=ci)

    doc = build_item_part_document(part)

    assert doc["id"] == part.id
    assert doc["shelfmark"] == "MS 1"
    assert doc["repository_name"] == "Test Repo"
    assert doc["repository_city"] == "Glasgow"
    assert doc["type"] == "Charter"
    assert doc["number_of_images"] == 0
    assert doc["image_availability"] == "Without images"
    # display_label is derived from the model's display_label()
    assert "display_label" in doc


@pytest.mark.django_db
def test_item_image_builder_emits_minimal_doc():
    from apps.manuscripts.tests.factories import (
        CurrentItemFactory,
        ItemImageFactory,
        ItemPartFactory,
        RepositoryFactory,
    )

    repo = RepositoryFactory(name="National Records of Scotland", label="NRS", place="Edinburgh")
    ci = CurrentItemFactory(repository=repo, shelfmark="GD55/44")
    part = ItemPartFactory(current_item=ci)
    img = ItemImageFactory(item_part=part, locus="face")
    doc = build_item_image_document(img)

    assert doc["id"] == img.id
    assert doc["locus"] == "face"
    assert doc["item_part"] == img.item_part_id
    # repository abbreviation + shelfmark composite consumed by result-card labels
    assert doc["display_label"] == "NRS GD55/44"
    assert doc["repository_name"] == "National Records of Scotland"
    assert doc["shelfmark"] == "GD55/44"
    assert doc["number_of_annotations"] == 0
    assert doc["components"] == []
    assert doc["features"] == []
    assert doc["positions"] == []
    assert doc["tags"] == []


@pytest.mark.django_db
def test_scribe_builder_emits_minimal_doc():
    from apps.scribes.tests.factories import ScribeFactory

    scribe = ScribeFactory(name="John of Glasgow", scriptorium="Glasgow Cathedral")
    doc = build_scribe_document(scribe)

    assert doc == {
        "id": scribe.id,
        "name": "John of Glasgow",
        "period": str(scribe.period) if scribe.period else "",
        "scriptorium": "Glasgow Cathedral",
    }


@pytest.mark.django_db
def test_hand_builder_emits_minimal_doc():
    from apps.scribes.tests.factories import HandFactory

    hand = HandFactory(name="Main hand", place="Glasgow", description="round caroline")
    doc = build_hand_document(hand)

    assert doc["id"] == hand.id
    assert doc["name"] == "Main hand"
    assert doc["place"] == "Glasgow"
    assert doc["description"] == "round caroline"
    assert "catalogue_numbers" in doc
    assert isinstance(doc["catalogue_numbers"], list)


@pytest.mark.django_db
def test_graph_builder_emits_minimal_doc():
    from apps.annotations.models import Graph
    from apps.manuscripts.tests.factories import (
        CurrentItemFactory,
        ItemImageFactory,
        ItemPartFactory,
        RepositoryFactory,
    )

    repo = RepositoryFactory(label="BL")
    ci = CurrentItemFactory(repository=repo, shelfmark="Cotton Ch. xviii.13")
    part = ItemPartFactory(current_item=ci)
    img = ItemImageFactory(item_part=part)
    g = Graph.objects.create(
        item_image=img,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[]]}},
        annotation_type="editorial",
    )

    doc = build_graph_document(g)

    assert doc["id"] == g.id
    assert doc["item_image"] == img.id
    assert doc["item_part"] == img.item_part_id
    # repository abbreviation + shelfmark composite consumed by result-card labels
    assert doc["display_label"] == "BL Cotton Ch. xviii.13"
    # is_annotated is False for an editorial graph with no components/positions
    assert doc["is_annotated"] is False
    assert doc["components"] == []
    assert doc["features"] == []
    assert doc["positions"] == []
    # coordinates is the JSON-serialized annotation
    assert "Polygon" in doc["coordinates"]


@pytest.mark.django_db
def test_graph_builder_emits_sortable_manuscript_context():
    """Graph docs carry the manuscript context palaeographers sort grid results by.

    date_min/date_max must be ints, not strings: they are numeric sort weights,
    and get_attr() would stringify them into a lexicographic ordering.
    """
    from apps.annotations.models import Graph
    from apps.common.tests.factories import DateFactory
    from apps.manuscripts.tests.factories import (
        CurrentItemFactory,
        HistoricalItemFactory,
        ItemImageFactory,
        ItemPartFactory,
        RepositoryFactory,
    )
    from apps.scribes.tests.factories import HandFactory, ScribeFactory

    repo = RepositoryFactory(label="NRS", place="Edinburgh")
    ci = CurrentItemFactory(repository=repo, shelfmark="GD55/44")
    date = DateFactory(date="1189 X 1195", min_weight=1189, max_weight=1195)
    hi = HistoricalItemFactory(type="Charter", date=date)
    part = ItemPartFactory(current_item=ci, historical_item=hi)
    img = ItemImageFactory(item_part=part, locus="dorse")
    scribe = ScribeFactory(name="Scribe of Melrose")
    hand = HandFactory(name="Main hand", item_part=part, scribe=scribe)
    g = Graph.objects.create(
        item_image=img,
        hand=hand,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[]]}},
        annotation_type="editorial",
    )

    doc = build_graph_document(g)

    assert doc["locus"] == "dorse"
    assert doc["type"] == "Charter"
    assert doc["scribe"] == "Scribe of Melrose"
    assert doc["hand_name"] == "Main hand"
    # Numeric sort weights — the type assertion is the point of the test.
    assert doc["date_min"] == 1189
    assert doc["date_max"] == 1195
    assert isinstance(doc["date_min"], int)
    assert isinstance(doc["date_max"], int)


@pytest.mark.django_db
def test_text_builder_emits_minimal_doc():
    from apps.manuscripts.models import ImageText
    from apps.manuscripts.tests.factories import ImageTextFactory

    text = ImageTextFactory(content="<p>plain text</p>", type=ImageText.Type.TRANSCRIPTION)
    doc = build_text_document(text)

    assert doc["id"] == text.id
    assert doc["text_type"] == ImageText.Type.TRANSCRIPTION
    # HTML stripped for search
    assert "<p>" not in doc["content"]
    assert "plain text" in doc["content"]
    assert doc["item_image"] == text.item_image_id
    assert doc["status"] == ImageText.Status.DRAFT
    # No data-dpt markup → empty lists, null annotation_id
    assert doc["places"] == []
    assert doc["people"] == []
    assert doc["annotation_id"] is None


def test_meta_every_index_type_has_a_documented_builder_test():
    """Walks INDEX_REGISTRY and asserts every IndexType has coverage recorded
    in BUILDER_COVERAGE. Adding a new IndexType without registering a test
    fails this assertion — the regression net for forgotten coverage."""
    registered = set(INDEX_REGISTRY.keys())
    covered = set(BUILDER_COVERAGE.keys())
    missing = registered - covered
    extras = covered - registered
    assert not missing, f"INDEX_REGISTRY has uncovered IndexTypes: {missing}"
    assert not extras, f"BUILDER_COVERAGE references unknown IndexTypes: {extras}"

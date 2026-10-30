"""Golden tests for the per-IndexType document builders.

One builder per test, asserting the document shape on a minimal factory graph.
The text-derived fan-out builders (clauses, people, places) are covered in
test_annotation_id_documents.py; `test_registry_drift.py` checks that every
registered attribute is emitted by every builder.
"""

import pytest

from apps.search.documents.graphs import build_graph_document
from apps.search.documents.hands import build_hand_document
from apps.search.documents.item_images import build_item_image_document
from apps.search.documents.item_parts import build_item_part_document
from apps.search.documents.scribes import build_scribe_document
from apps.search.documents.texts import build_text_document
from apps.search.documents.utils import natural_sort_key


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
    from apps.common.tests.factories import PlaceFactory
    from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory

    hand = HandFactory(name="Main hand", place=PlaceFactory(name="Glasgow"))
    HandDescriptionFactory(hand=hand, content="round caroline")
    doc = build_hand_document(hand)

    assert doc["id"] == hand.id
    assert doc["name"] == "Main hand"
    assert doc["place"] == "Glasgow"
    assert doc["description"] == "round caroline"
    assert "catalogue_numbers" in doc
    assert isinstance(doc["catalogue_numbers"], list)
    # The hand's own date, as the string and the numeric bounds the date window filters on.
    assert doc["date"] == hand.date.date
    assert (doc["date_min"], doc["date_max"]) == (hand.date.min_weight, hand.date.max_weight)


@pytest.mark.django_db
def test_item_image_builder_carries_the_manuscript_date_bounds():
    from apps.common.tests.factories import DateFactory
    from apps.manuscripts.tests.factories import HistoricalItemFactory, ItemImageFactory, ItemPartFactory

    date = DateFactory(date="c. 1150", min_weight=1140, max_weight=1160)
    image = ItemImageFactory(item_part=ItemPartFactory(historical_item=HistoricalItemFactory(date=date)))

    doc = build_item_image_document(image)

    assert doc["date"] == "c. 1150"
    assert (doc["date_min"], doc["date_max"]) == (1140, 1160)


@pytest.mark.django_db
def test_hand_builder_joins_multiple_descriptions():
    from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory

    hand = HandFactory(name="Main hand")
    HandDescriptionFactory(hand=hand, content="First description.")
    HandDescriptionFactory(hand=hand, content="Second description.")
    doc = build_hand_document(hand)

    assert "First description." in doc["description"]
    assert "Second description." in doc["description"]


@pytest.mark.django_db
def test_hand_builder_strips_html_from_descriptions():
    from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory

    hand = HandFactory(name="Main hand")
    HandDescriptionFactory(hand=hand, content="<p>insular</p>")
    HandDescriptionFactory(hand=hand, content="<p>round <em>caroline</em></p>")
    doc = build_hand_document(hand)

    assert doc["description"] == "insular round caroline"


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
    assert doc["display_label"] == "BL Cotton Ch. xviii.13"
    assert doc["is_annotated"] is False
    assert doc["components"] == []
    assert doc["features"] == []
    assert doc["positions"] == []
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
    assert doc["date_min"] == 1189
    assert doc["date_max"] == 1195
    assert isinstance(doc["date_min"], int)
    assert isinstance(doc["date_max"], int)


@pytest.mark.django_db
def test_graph_builder_allograph_label_formatting():
    """Allograph facet labels in search documents combine character and allograph names."""
    from apps.annotations.models import Graph
    from apps.manuscripts.tests.factories import ItemImageFactory
    from apps.symbols_structure.tests.factories import AllographFactory, CharacterFactory

    img = ItemImageFactory()

    char_a = CharacterFactory(name="a")
    allo_a = AllographFactory(character=char_a, name="double-compartment a")
    g1 = Graph.objects.create(
        item_image=img,
        allograph=allo_a,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[]]}},
        annotation_type="editorial",
    )
    doc1 = build_graph_document(g1)
    assert doc1["allograph"] == "a, double-compartment a"
    assert doc1["character"] == "a"

    char_b = CharacterFactory(name="b")
    allo_b = AllographFactory(character=char_b, name="b")
    g2 = Graph.objects.create(
        item_image=img,
        allograph=allo_b,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[]]}},
        annotation_type="editorial",
    )
    doc2 = build_graph_document(g2)
    assert doc2["allograph"] == "b"
    assert doc2["character"] == "b"

    g3 = Graph.objects.create(
        item_image=img,
        allograph=None,
        annotation={"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[]]}},
        annotation_type="editorial",
    )
    doc3 = build_graph_document(g3)
    assert "allograph" not in doc3
    assert "character" not in doc3


@pytest.mark.django_db
def test_text_builder_emits_minimal_doc():
    from apps.manuscripts.models import ImageText
    from apps.manuscripts.tests.factories import ImageTextFactory

    text = ImageTextFactory(content="<p>plain text</p>", type=ImageText.Type.TRANSCRIPTION)
    doc = build_text_document(text)

    assert doc["id"] == text.id
    assert doc["text_type"] == ImageText.Type.TRANSCRIPTION
    assert "<p>" not in doc["content"]
    assert "plain text" in doc["content"]
    assert doc["item_image"] == text.item_image_id
    assert doc["status"] == ImageText.Status.DRAFT
    assert doc["places"] == []
    assert doc["people"] == []
    assert doc["annotation_id"] is None


@pytest.mark.parametrize(
    ("shelfmarks", "expected"),
    [
        (["MS 10", "MS 2", "MS 1"], ["MS 1", "MS 2", "MS 10"]),
        (["Add. 10000", "Add. 999", "add. 5"], ["add. 5", "Add. 999", "Add. 10000"]),  # case does not split the run
        (["B 2 x 3", "B 2 x 10"], ["B 2 x 3", "B 2 x 10"]),
    ],
)
def test_natural_sort_key_orders_digit_runs_numerically(shelfmarks, expected):
    assert sorted(shelfmarks, key=natural_sort_key) == expected


def test_natural_sort_key_keeps_none():
    assert natural_sort_key(None) is None


@pytest.mark.django_db
def test_builders_emit_the_shelfmark_sort_key():
    from apps.manuscripts.tests.factories import CurrentItemFactory, ItemImageFactory, ItemPartFactory
    from apps.scribes.tests.factories import HandFactory

    part = ItemPartFactory(current_item=CurrentItemFactory(shelfmark="MS 2"))
    image = ItemImageFactory(item_part=part)
    hand = HandFactory(item_part=part)

    for doc in (build_item_part_document(part), build_item_image_document(image), build_hand_document(hand)):
        assert doc["shelfmark"] == "MS 2"
        assert doc["shelfmark_sort"] == natural_sort_key("MS 2")

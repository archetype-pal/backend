"""The tutor's tools: their schemas, what each looks up, and where its boxes land."""

import json
from unittest import mock

import pytest

from apps.annotations.models import Graph
from apps.annotations.tests.factories import GraphComponentFactory, GraphFactory
from apps.common.tests.factories import DateFactory
from apps.learn.services import tools
from apps.manuscripts.tests.factories import HistoricalItemFactory, ItemImageFactory, ItemPartFactory
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import (
    AllographComponentFactory,
    AllographComponentFeatureFactory,
    AllographFactory,
    CharacterFactory,
    ComponentFactory,
    FeatureFactory,
)
from apps.vision import images

from .conftest import jpeg, ring


def desk(**overrides):
    values = {"picture": jpeg(800, 600), "width": 800, "height": 600}
    values.update(overrides)
    return tools.Desk(**values)


def _walk(schema, path="input_schema"):
    """Every object in a schema, with where it is."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield path, schema
        for key, value in schema.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            yield from _walk(value, f"{path}[{index}]")


class TestDefinitions:
    def test_every_tool_is_strict(self):
        assert all(tool["strict"] is True for tool in tools.definitions(annotated=True))

    def test_every_object_requires_all_its_properties_and_allows_no_others(self):
        # What strict tool use asks of a schema; an object that does not is refused by the API.
        for tool in tools.definitions(annotated=True):
            for path, schema in _walk(tool["input_schema"]):
                assert schema.get("additionalProperties") is False, f"{tool['name']} {path}"
                assert sorted(schema["required"]) == sorted(schema["properties"]), f"{tool['name']} {path}"

    def test_no_schema_uses_a_constraint_strict_tool_use_does_not_take(self):
        text = json.dumps(tools.definitions(annotated=True))

        for keyword in ('"minimum"', '"maximum"', '"minLength"', '"maxLength"', '"maxItems"', '"pattern"'):
            assert keyword not in text

    def test_the_experts_annotations_are_offered_only_for_an_annotated_page(self):
        def names(annotated):
            return [tool["name"] for tool in tools.definitions(annotated=annotated)]

        assert tools.EXPERT_ANNOTATIONS in names(True)
        assert tools.EXPERT_ANNOTATIONS not in names(False)
        assert names(False) == [
            tools.LOOK_CLOSER,
            tools.DESCRIBE_ALLOGRAPH,
            tools.CORPUS_EXAMPLES,
            tools.PRESENT_WALKTHROUGH,
            tools.REPLY,
        ]

    def test_the_definitions_are_the_same_every_time(self):
        # A conversation's tools are checked byte for byte against the turn that produced its thinking.
        assert json.dumps(tools.definitions(annotated=True)) == json.dumps(tools.definitions(annotated=True))


@pytest.mark.django_db
class TestTaxonomy:
    def test_each_form_is_listed_with_its_id_and_type(self):
        letter = CharacterFactory(name="s", type="letter")
        long_s = AllographFactory(character=letter, name="long")
        plain = AllographFactory(character=CharacterFactory(name="b", type="letter"), name="b")

        listed = tools.taxonomy().splitlines()

        assert f"{long_s.pk}: s, long (letter)" in listed
        # A form named as its character is listed once, by the character.
        assert f"{plain.pk}: b (letter)" in listed

    def test_placeholders_are_left_out(self):
        stroke = CharacterFactory(name="stroke", type="abbreviation")
        AllographFactory(character=stroke, name="unmapped_allographs")
        AllographFactory(character=CharacterFactory(name="_unspecified"), name="_unspecified")

        assert tools.taxonomy() == ""


@pytest.mark.django_db
class TestLookCloser:
    def test_the_region_comes_back_enlarged_with_its_scale(self):
        result = tools.run(
            tools.LOOK_CLOSER,
            {"reason": "to read line 1", "box": {"x": 0, "y": 0, "width": 350, "height": 100}},
            desk(),
        )

        assert not result.error
        assert "enlarged 4.0×" in result.text
        ((caption, data),) = result.images
        assert caption == result.text
        assert data[:3] == b"\xff\xd8\xff"
        assert result.progress == "Looking closer: to read line 1"

    def test_a_box_off_the_picture_is_an_error_naming_its_size(self):
        result = tools.run(
            tools.LOOK_CLOSER, {"reason": "", "box": {"x": 900, "y": 0, "width": 10, "height": 10}}, desk()
        )

        assert result.error
        assert "800 by 600" in result.text
        assert result.images == []

    def test_an_unknown_tool_is_an_error(self):
        result = tools.run("delete_everything", {}, desk())

        assert result.error
        assert "delete_everything" in result.text


@pytest.mark.django_db
class TestDescribeAllograph:
    def test_its_parts_features_and_how_often_each_is_recorded(self):
        form = AllographFactory(character=CharacterFactory(name="a", type="letter"), name="with head")
        head = ComponentFactory(name="Head")
        part = AllographComponentFactory(allograph=form, component=head)
        broken, plain = FeatureFactory(name="broken arc"), FeatureFactory(name="rounded")
        AllographComponentFeatureFactory(allograph_component=part, feature=broken)
        AllographComponentFeatureFactory(allograph_component=part, feature=plain)
        for _ in range(3):
            GraphComponentFactory(graph=GraphFactory(allograph=form), component=head).features.add(broken)
        GraphComponentFactory(graph=GraphFactory(allograph=form), component=head).features.add(plain)
        GraphFactory(allograph=form)

        result = tools.run(tools.DESCRIBE_ALLOGRAPH, {"allograph_id": form.pk}, desk())
        answer = json.loads(result.text)

        assert answer["character"] == "a"
        assert answer["form"] == "with head"
        assert answer["annotated_examples"] == 5
        assert answer["examples_with_features_recorded"] == 4
        assert answer["components"] == [
            {
                "component": "Head",
                "features_experts_record": ["broken arc", "rounded"],
                "recorded_on_examples": {"broken arc": 3, "rounded": 1},
            }
        ]
        assert result.progress == "Reading up on a (with head)"

    def test_a_form_that_names_no_features_for_a_part_takes_the_parts_own(self):
        form = AllographFactory()
        shaft = ComponentFactory(name="Shaft")
        shaft.features.add(FeatureFactory(name="forked"), FeatureFactory(name="looped"))
        AllographComponentFactory(allograph=form, component=shaft)

        answer = json.loads(tools.run(tools.DESCRIBE_ALLOGRAPH, {"allograph_id": form.pk}, desk()).text)

        assert answer["components"][0]["features_experts_record"] == ["forked", "looped"]

    def test_the_hands_with_most_examples_come_first(self):
        form = AllographFactory()
        busy, quiet = HandFactory(name="Main Hand"), HandFactory(name="Second Hand")
        for _ in range(3):
            GraphFactory(allograph=form, hand=busy)
        GraphFactory(allograph=form, hand=quiet)

        answer = json.loads(tools.run(tools.DESCRIBE_ALLOGRAPH, {"allograph_id": form.pk}, desk()).text)

        assert [(hand["hand"], hand["examples"]) for hand in answer["hands_with_most_examples"]] == [
            ("Main Hand", 3),
            ("Second Hand", 1),
        ]

    def test_examples_are_counted_by_the_quarter_century_of_their_charter(self):
        form = AllographFactory()

        def on(low, high):
            page = ItemImageFactory(
                item_part=ItemPartFactory(
                    historical_item=HistoricalItemFactory(date=DateFactory(min_weight=low, max_weight=high))
                )
            )
            GraphFactory(allograph=form, item_image=page)

        on(1150, 1160)
        on(1170, 1174)
        on(1190, 1210)

        answer = json.loads(tools.run(tools.DESCRIBE_ALLOGRAPH, {"allograph_id": form.pk}, desk()).text)

        assert answer["examples_by_date_of_charter"] == {"1150-1174": 2, "1200-1224": 1}

    def test_an_unknown_or_placeholder_form_is_an_error(self):
        placeholder = AllographFactory(name="unmapped_allographs")

        for value in (999999, placeholder.pk, "a"):
            result = tools.run(tools.DESCRIBE_ALLOGRAPH, {"allograph_id": value}, desk())
            assert result.error
            assert "no allograph" in result.text

    def test_editorial_annotations_are_not_counted(self):
        form = AllographFactory()
        GraphFactory(allograph=form)
        GraphFactory(allograph=form, annotation_type=Graph.AnnotationType.EDITORIAL)

        answer = json.loads(tools.run(tools.DESCRIBE_ALLOGRAPH, {"allograph_id": form.pk}, desk()).text)

        assert answer["annotated_examples"] == 1


@pytest.mark.django_db
class TestChooseExamples:
    def test_one_example_from_each_hand_comes_before_a_second_from_any(self):
        form = AllographFactory()
        first, second = HandFactory(), HandFactory()
        a1 = GraphFactory(allograph=form, hand=first)
        GraphFactory(allograph=form, hand=first, item_image=a1.item_image)
        b1 = GraphFactory(allograph=form, hand=second)

        chosen = tools.choose_examples(form, 2)

        assert {graph.pk for graph in chosen} == {a1.pk, b1.pk}

    def test_examples_with_features_recorded_come_first(self):
        form = AllographFactory()
        bare = GraphFactory(allograph=form)
        described = GraphFactory(allograph=form)
        GraphComponentFactory(graph=described).features.add(FeatureFactory())

        assert [graph.pk for graph in tools.choose_examples(form, 2)] == [described.pk, bare.pk]

    def test_the_lessons_own_page_is_left_out(self):
        form = AllographFactory()
        here = GraphFactory(allograph=form)
        elsewhere = GraphFactory(allograph=form)

        chosen = tools.choose_examples(form, 5, exclude_page=here.item_image_id)

        assert [graph.pk for graph in chosen] == [elsewhere.pk]

    def test_more_are_taken_from_a_hand_already_shown_when_there_are_no_others(self):
        form = AllographFactory()
        hand = HandFactory()
        graphs = [GraphFactory(allograph=form, hand=hand) for _ in range(3)]

        assert sorted(graph.pk for graph in tools.choose_examples(form, 3)) == sorted(graph.pk for graph in graphs)


@pytest.mark.django_db
class TestCorpusExamples:
    def test_each_example_comes_with_its_details_before_its_picture_and_is_marked_seen(self):
        form = AllographFactory(character=CharacterFactory(name="g"), name="g")
        graph = GraphFactory(allograph=form, annotation=ring(10, 10, 50, 60))
        here = desk()

        with mock.patch.object(tools, "_crop", return_value=b"crop-bytes") as crop:
            result = tools.run(tools.CORPUS_EXAMPLES, {"reason": "", "allograph_id": form.pk, "count": 3}, here)

        crop.assert_called_once()
        assert not result.error
        ((details, data),) = result.images
        assert data == b"crop-bytes"
        assert json.loads(details)["glyph_id"] == graph.pk
        assert graph.pk in here.seen
        assert result.progress == "Finding examples of g in other charters"

    def test_an_example_that_cannot_be_fetched_is_skipped_and_not_marked_seen(self):
        form = AllographFactory()
        kept, lost = GraphFactory(allograph=form), GraphFactory(allograph=form)
        here = desk()

        def crop(graph):
            if graph.pk == lost.pk:
                raise images.ImageUnavailable("down")
            return b"ok"

        with mock.patch.object(tools, "_crop", side_effect=crop):
            result = tools.run(tools.CORPUS_EXAMPLES, {"reason": "", "allograph_id": form.pk, "count": 2}, here)

        assert len(result.images) == 1
        assert here.seen == {kept.pk}

    def test_none_fetched_is_an_error(self):
        form = AllographFactory()
        GraphFactory(allograph=form)

        with mock.patch.object(tools, "_crop", side_effect=images.ImageUnavailable("down")):
            result = tools.run(tools.CORPUS_EXAMPLES, {"reason": "", "allograph_id": form.pk, "count": 2}, desk())

        assert result.error
        assert "image server" in result.text

    def test_a_form_with_no_examples_elsewhere_is_an_error(self):
        form = AllographFactory()
        graph = GraphFactory(allograph=form)

        result = tools.run(
            tools.CORPUS_EXAMPLES,
            {"reason": "", "allograph_id": form.pk, "count": 2},
            desk(page=graph.item_image),
        )

        assert result.error
        assert "No other charter" in result.text

    @pytest.mark.parametrize(("asked", "shown"), [(0, 1), (3, 3), (50, tools.MAX_EXAMPLES)])
    def test_the_count_is_kept_between_one_and_the_most(self, asked, shown):
        form = AllographFactory()
        for _ in range(tools.MAX_EXAMPLES + 2):
            GraphFactory(allograph=form)

        with mock.patch.object(tools, "_crop", return_value=b"ok"):
            result = tools.run(tools.CORPUS_EXAMPLES, {"reason": "", "allograph_id": form.pk, "count": asked}, desk())

        assert len(result.images) == shown

    def test_an_example_that_cannot_be_fetched_is_replaced_by_the_next(self):
        form = AllographFactory()
        lost, spare, unneeded = (GraphFactory(allograph=form) for _ in range(3))
        here = desk()

        def crop(graph):
            if graph.pk == lost.pk:
                raise images.ImageUnavailable("down")
            return b"ok"

        with mock.patch.object(tools, "_crop", side_effect=crop):
            result = tools.run(tools.CORPUS_EXAMPLES, {"reason": "", "allograph_id": form.pk, "count": 1}, here)

        assert [json.loads(details)["glyph_id"] for details, _ in result.images] == [spare.pk]
        assert here.seen == {spare.pk}
        assert unneeded.pk not in here.seen


class TestGeometry:
    def test_a_glyphs_region_has_room_around_it_and_is_flipped_to_y_down(self):
        # 40 wide and 50 high, its top 940 pixels below the top of a 1000-pixel page.
        region = tools.glyph_region(ring(100, 10, 140, 60), page_height=1000)

        assert region == "90,927,60,75"

    def test_a_region_does_not_start_off_the_page(self):
        assert tools.glyph_region(ring(0, 990, 40, 1000), page_height=1000).startswith("0,0,")

    @pytest.mark.parametrize("annotation", [{"test": "test"}, "not json", ring(10, 10, 10, 20), None])
    def test_an_unreadable_ring_has_no_region(self, annotation):
        assert tools.glyph_region(annotation, page_height=1000) is None

    def test_a_stored_ring_lands_on_the_picture_scaled_and_flipped(self):
        # A 2000 by 1500 page shown as an 800 by 600 picture: everything at 0.4.
        here = desk(page_size=(2000, 1500))

        box = tools.picture_box(ring(500, 1000, 600, 1250), here)

        assert box == {"x": 200, "y": 100, "width": 40, "height": 100}

    def test_a_ring_is_not_placed_while_the_page_is_unmeasured(self):
        assert tools.picture_box(ring(500, 1000, 600, 1250), desk()) is None


@pytest.mark.django_db
class TestExpertAnnotations:
    def test_the_pages_glyphs_come_grouped_by_form_with_boxes_on_the_picture(self):
        page = ItemImageFactory()
        letter = AllographFactory(character=CharacterFactory(name="d"), name="d")
        first = GraphFactory(item_image=page, allograph=letter, annotation=ring(500, 1000, 600, 1250))
        GraphFactory(item_image=page, annotation_type=Graph.AnnotationType.EDITORIAL, allograph=None, hand=None)
        GraphFactory(allograph=letter)
        here = desk(page=page, page_size=(2000, 1500))

        result = tools.run(tools.EXPERT_ANNOTATIONS, {"allograph_id": None}, here)
        answer = json.loads(result.text)

        assert answer["glyphs"] == 1
        (group,) = answer["letter_forms"]
        assert group["allograph_id"] == letter.pk
        assert group["letter_form"] == "d"
        assert group["glyphs"][0]["glyph_id"] == first.pk
        assert group["glyphs"][0]["box"] == [200, 100, 40, 100]
        assert here.seen == {first.pk}

    def test_one_form_can_be_asked_for(self):
        page = ItemImageFactory()
        wanted, other = AllographFactory(), AllographFactory()
        GraphFactory(item_image=page, allograph=wanted, annotation=ring(0, 0, 10, 10))
        GraphFactory(item_image=page, allograph=other, annotation=ring(0, 0, 10, 10))

        answer = json.loads(
            tools.run(tools.EXPERT_ANNOTATIONS, {"allograph_id": wanted.pk}, desk(page=page, page_size=(800, 600))).text
        )

        assert [group["allograph_id"] for group in answer["letter_forms"]] == [wanted.pk]

    def test_the_page_is_measured_when_its_size_is_not_known(self):
        page = ItemImageFactory()
        GraphFactory(item_image=page, annotation=ring(0, 0, 10, 10))
        here = desk(page=page)

        with mock.patch.object(images, "dimensions", return_value=(800, 600)) as measure:
            tools.run(tools.EXPERT_ANNOTATIONS, {"allograph_id": None}, here)

        measure.assert_called_once_with(page)
        assert here.page_size == (800, 600)

    def test_a_picture_of_the_students_own_has_no_expert_annotations(self):
        result = tools.run(tools.EXPERT_ANNOTATIONS, {"allograph_id": None}, desk())

        assert result.error
        assert "not from the corpus" in result.text


@pytest.mark.django_db
class TestShown:
    def test_a_cited_glyph_is_resolved_to_its_crop_and_provenance(self):
        graph = GraphFactory(annotation=ring(100, 10, 140, 60))

        with (
            mock.patch.object(images, "dimensions", return_value=(800, 1000)),
            mock.patch.object(images, "identifier", return_value="https://iiif.example/page"),
        ):
            shown = tools.shown([graph.pk])

        entry = shown[str(graph.pk)]
        assert entry["crop_url"] == "https://iiif.example/page/90,927,60,75/%5E!240,240/0/default.jpg"
        assert entry["item_image"] == graph.item_image_id
        assert entry["historical_item"] == graph.item_image.item_part.historical_item_id
        assert entry["allograph_id"] == graph.allograph_id

    def test_a_glyph_on_a_page_that_cannot_be_measured_is_shown_without_a_crop(self):
        graph = GraphFactory(annotation=ring(100, 10, 140, 60))

        with mock.patch.object(images, "dimensions", side_effect=images.ImageUnavailable("down")):
            assert tools.shown([graph.pk])[str(graph.pk)]["crop_url"] is None

    def test_an_editorial_glyph_is_never_shown(self):
        graph = GraphFactory(annotation_type=Graph.AnnotationType.EDITORIAL, allograph=None, hand=None)

        assert tools.shown([graph.pk]) == {}

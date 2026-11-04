"""W2.3 — the network and its GEXF export."""

from xml.etree import ElementTree as ET

import pytest

from apps.diplomatic import network
from apps.diplomatic.models import CharterEntity, Relation
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory, catalogued_item_part
from apps.scribes.tests.factories import HandFactory, ScribeFactory


def _charter(text):
    return f"charter:{text.item_image.item_part_id}"


def _witness(text, name="Walterus"):
    return CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name=name)


@pytest.mark.django_db
class TestBuild:
    def test_witnesses_and_charters_become_nodes_and_edges(self):
        text = ImageTextFactory()
        _witness(text)
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.GRANTER, name="David rex")

        graph = network.build()

        assert graph.nodes[_charter(text)]["kind"] == "charter"
        assert graph.nodes["person:walterus"]["label"] == "Walterus"
        assert len(graph.edges) == 2

    def test_a_charter_is_named_as_on_the_rest_of_the_site_and_carries_its_item_part(self):
        text = ImageTextFactory()
        _witness(text)
        part = text.item_image.item_part

        charter = network.build().nodes[_charter(text)]

        assert charter["label"] == part.display_label()
        assert charter["record"] == part.pk

    def test_the_face_and_the_dorse_of_one_charter_are_one_node(self):
        face = ImageTextFactory()
        dorse = ImageTextFactory(item_image=ItemImageFactory(item_part=face.item_image.item_part))
        _witness(face)
        CharterEntity.objects.create(image_text=dorse, role=CharterEntity.Role.PLACE, name="Edinburgh")

        graph = network.build()

        assert [key for key, node in graph.nodes.items() if node["kind"] == "charter"] == [_charter(face)]
        assert {(edge["source"], edge["target"]) for edge in graph.edges} == {
            ("person:walterus", _charter(face)),
            (_charter(face), "place:edinburgh"),
        }

    def test_dates_and_transaction_types_add_no_node(self):
        text = ImageTextFactory()
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.DATE, name="1150")
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.TRANSACTION, name="grant")

        graph = network.build()

        assert graph.nodes == {}
        assert graph.edges == []

    def test_two_spellings_of_a_name_stay_two_people(self):
        first, second = ImageTextFactory(), ImageTextFactory()
        _witness(first, "Walterus filius Alani")
        _witness(second, "Walter fitz Alan")

        graph = network.build()

        # Merging them is a prosopographical judgement; doing it here would
        # manufacture a connection nobody asserted.
        people = [key for key, node in graph.nodes.items() if node["kind"] == "person"]
        assert len(people) == 2

    def test_case_and_spacing_do_not_split_one_person(self):
        first, second = ImageTextFactory(), ImageTextFactory()
        _witness(first, "Walterus")
        _witness(second, " walterus ")

        graph = network.build()

        assert len([key for key, node in graph.nodes.items() if node["kind"] == "person"]) == 1

    def test_relations_connect_people_directly_and_name_the_charter_that_states_them(self):
        text = ImageTextFactory()
        Relation.objects.create(
            image_text=text, subject="Walterus", predicate=Relation.Predicate.WITNESSED_BY, object="David"
        )

        graph = network.build()

        assert {"person:walterus", "person:david"} <= set(graph.nodes)
        assert graph.edges == [
            {
                "source": "person:walterus",
                "target": "person:david",
                "relation": "witnessed_by",
                "charter": _charter(text),
            }
        ]
        assert graph.nodes[_charter(text)]["kind"] == "charter"

    def test_an_empty_corpus_gives_an_empty_graph_not_an_error(self):
        graph = network.build()

        assert graph.nodes == {}
        assert graph.density == 0.0


@pytest.mark.django_db
class TestScribes:
    def test_the_scribe_of_a_charter_in_the_network_joins_it(self):
        text = ImageTextFactory()
        _witness(text)
        scribe = ScribeFactory(name="Barrow, Scribe Ab")
        HandFactory(scribe=scribe, item_part=text.item_image.item_part)

        graph = network.build()

        assert graph.nodes[f"scribe:{scribe.pk}"] == {
            "label": "Barrow, Scribe Ab",
            "kind": "scribe",
            "record": scribe.pk,
        }
        assert {"source": f"scribe:{scribe.pk}", "target": _charter(text), "relation": "scribe", "charter": ""} in (
            graph.edges
        )

    def test_two_hands_of_one_scribe_on_a_charter_are_one_edge(self):
        text = ImageTextFactory()
        _witness(text)
        scribe = ScribeFactory()
        HandFactory.create_batch(2, scribe=scribe, item_part=text.item_image.item_part)

        graph = network.build()

        assert [edge for edge in graph.edges if edge["relation"] == "scribe"] == [
            {"source": f"scribe:{scribe.pk}", "target": _charter(text), "relation": "scribe", "charter": ""}
        ]

    def test_a_scribe_whose_charters_have_no_approved_names_stays_out(self):
        HandFactory()

        assert network.build().nodes == {}

    def test_the_imports_placeholder_scribe_joins_nothing(self):
        # The DigiPal import filed every unattributed hand under this one row.
        placeholder = ScribeFactory(pk=-1, name="[name] update records relations later")
        first, second = ImageTextFactory(), ImageTextFactory()
        for text in (first, second):
            _witness(text, f"witness {text.pk}")
            HandFactory(scribe=placeholder, item_part=text.item_image.item_part)

        graph = network.build()

        assert "scribe:-1" not in graph.nodes
        assert all(edge["relation"] != "scribe" for edge in graph.edges)


@pytest.mark.django_db
class TestReadableTexts:
    def test_only_what_was_read_from_the_given_texts_is_drawn(self):
        live = ImageTextFactory(status=ImageText.Status.LIVE)
        draft = ImageTextFactory()
        _witness(live, "Walterus")
        _witness(draft, "Secret witness")
        Relation.objects.create(image_text=draft, subject="a", predicate=Relation.Predicate.GRANTED_BY, object="b")
        scribe = ScribeFactory()
        HandFactory(scribe=scribe, item_part=draft.item_image.item_part)

        graph = network.build(ImageText.objects.filter(pk=live.pk).values("pk"))

        assert set(graph.nodes) == {"person:walterus", _charter(live)}

    @pytest.mark.parametrize("charters", [1, 6])
    def test_building_costs_no_query_per_charter(self, django_assert_max_num_queries, charters):
        scribe = ScribeFactory()
        for _ in range(charters):
            # Known only by catalogue number, the costlier label to name.
            text = ImageTextFactory(item_image=ItemImageFactory(item_part=catalogued_item_part()))
            _witness(text)
            Relation.objects.create(image_text=text, subject="a", predicate=Relation.Predicate.GRANTED_BY, object="b")
            HandFactory(scribe=scribe, item_part=text.item_image.item_part)

        # Entities, relations, the charters with their catalogue numbers, and the scribes.
        with django_assert_max_num_queries(6):
            network.build()


class TestJson:
    def test_the_view_gets_every_node_with_its_id_and_every_edge(self):
        graph = network.Graph()
        graph.add_node("person:walterus", "Walterus", "person")
        graph.add_node("charter:7", "GD55/30", "charter", record=7)
        graph.add_edge("person:walterus", "charter:7", "witness")

        assert network.to_json(graph) == {
            "nodes": [
                {"id": "charter:7", "label": "GD55/30", "kind": "charter", "record": 7},
                {"id": "person:walterus", "label": "Walterus", "kind": "person", "record": None},
            ],
            "edges": [{"source": "person:walterus", "target": "charter:7", "relation": "witness", "charter": ""}],
        }


@pytest.mark.django_db
class TestGexf:
    NS = {"g": network.GEXF_NS}

    def test_the_export_parses_and_carries_the_kinds_and_records(self):
        text = ImageTextFactory()
        _witness(text)
        part = text.item_image.item_part

        document = ET.fromstring(network.to_gexf(network.build()))

        nodes = {node.get("label"): node for node in document.findall(".//g:nodes/g:node", self.NS)}
        assert set(nodes) == {"Walterus", part.display_label()}
        assert document.findall(".//g:edges/g:edge", self.NS)[0].get("label") == "witness"

        def values(node):
            return {value.get("for"): value.get("value") for value in node.findall(".//g:attvalue", self.NS)}

        assert values(nodes[part.display_label()]) == {"kind": "charter", "record": str(part.pk)}
        assert values(nodes["Walterus"]) == {"kind": "person"}

    def test_an_empty_graph_still_produces_valid_gexf(self):
        document = ET.fromstring(network.to_gexf(network.build()))

        assert document.tag.endswith("gexf")

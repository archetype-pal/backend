"""W2.3 — the network and its GEXF export."""

from xml.etree import ElementTree as ET

import pytest

from apps.diplomatic import network
from apps.diplomatic.models import CharterEntity, Relation
from apps.manuscripts.tests.factories import ImageTextFactory


@pytest.mark.django_db
class TestBuild:
    def test_witnesses_and_charters_become_nodes_and_edges(self):
        text = ImageTextFactory()
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name="Walterus")
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.GRANTER, name="David rex")

        graph = network.build()

        assert graph.nodes[f"charter:{text.pk}"]["kind"] == "charter"
        assert graph.nodes["person:walterus"]["label"] == "Walterus"
        assert len(graph.edges) == 2

    def test_two_spellings_of_a_name_stay_two_people(self):
        first, second = ImageTextFactory(), ImageTextFactory()
        CharterEntity.objects.create(image_text=first, role=CharterEntity.Role.WITNESS, name="Walterus filius Alani")
        CharterEntity.objects.create(image_text=second, role=CharterEntity.Role.WITNESS, name="Walter fitz Alan")

        graph = network.build()

        # Merging them is a prosopographical judgement; doing it here would
        # manufacture a connection nobody asserted.
        people = [key for key, node in graph.nodes.items() if node["kind"] == "person"]
        assert len(people) == 2

    def test_case_and_spacing_do_not_split_one_person(self):
        first, second = ImageTextFactory(), ImageTextFactory()
        CharterEntity.objects.create(image_text=first, role=CharterEntity.Role.WITNESS, name="Walterus")
        CharterEntity.objects.create(image_text=second, role=CharterEntity.Role.WITNESS, name=" walterus ")

        graph = network.build()

        assert len([key for key, node in graph.nodes.items() if node["kind"] == "person"]) == 1

    def test_relations_connect_people_directly(self):
        text = ImageTextFactory()
        Relation.objects.create(
            image_text=text, subject="Walterus", predicate=Relation.Predicate.WITNESSED_BY, object="David"
        )

        graph = network.build()

        assert {"person:walterus", "person:david"} <= set(graph.nodes)
        assert graph.edges[0]["relation"] == "witnessed_by"

    def test_an_empty_corpus_gives_an_empty_graph_not_an_error(self):
        graph = network.build()

        assert graph.nodes == {}
        assert graph.density == 0.0


@pytest.mark.django_db
class TestGexf:
    def test_the_export_parses_and_carries_the_kinds(self):
        text = ImageTextFactory()
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name="Walterus")

        document = ET.fromstring(network.to_gexf(network.build()))

        namespace = {"g": network.GEXF_NS}
        nodes = document.findall(".//g:nodes/g:node", namespace)
        assert {node.get("label") for node in nodes} == {"Walterus", f"Charter {text.pk}"}
        assert document.findall(".//g:edges/g:edge", namespace)[0].get("label") == "witness"

    def test_an_empty_graph_still_produces_valid_gexf(self):
        document = ET.fromstring(network.to_gexf(network.build()))

        assert document.tag.endswith("gexf")

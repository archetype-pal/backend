"""W2.3 — the witness and scribe network, and its GEXF export.

Built from approved entities and relations plus the scribe attributions the
corpus already has. No model runs here: the network is a view of what humans
accepted, which is why it can be built and checked today while the pipelines
that feed it wait on a key.

A charter is its item part, the document, rather than one of its texts: the
face and the dorse of one charter are one node.

GEXF because the roadmap asks for it by name — the point is that the graph is
usable in Gephi and the standard network-analysis tools, not only in a view of
ours. A network you cannot take away is a picture, not data.
"""

from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

from apps.diplomatic.models import CharterEntity, Relation
from apps.manuscripts.models import ItemPart
from apps.scribes.models import Hand

GEXF_NS = "http://gexf.net/1.3"
VIZ_NS = "http://gexf.net/1.3/viz"

# The roles that tie a name to a charter. A date or a transaction type is a
# fact about the charter, not someone or somewhere it connects.
PERSON_ROLES = (CharterEntity.Role.GRANTER, CharterEntity.Role.BENEFICIARY, CharterEntity.Role.WITNESS)


@dataclass
class Graph:
    """People, places and charters, and what connects them."""

    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)

    def add_node(self, key: str, label: str, kind: str, record: int | None = None) -> None:
        # `record` is the row a charter or a scribe is (its item part, the
        # scribe), so a reader can open it; a name read in a text has none.
        self.nodes.setdefault(key, {"label": label, "kind": kind, "record": record})

    def add_edge(self, source: str, target: str, relation: str, charter: str = "") -> None:
        self.edges.append({"source": source, "target": target, "relation": relation, "charter": charter})

    @property
    def density(self) -> float:
        n = len(self.nodes)
        return (2 * len(self.edges)) / (n * (n - 1)) if n > 1 else 0.0


def _person_key(name: str) -> str:
    # Names are keyed on their surface form. Two spellings of one man stay two
    # nodes: merging them is a prosopographical judgement, and doing it silently
    # would manufacture connections nobody asserted.
    return f"person:{name.strip().lower()}"


def _place_key(name: str) -> str:
    return f"place:{name.strip().lower()}"


def build(texts: Any = None) -> Graph:
    """The network as it stands, from approved rows only.

    `texts` (ImageText pks) limits it to what was read from those texts, which
    is how the public network leaves drafts out. None is the whole corpus, for
    an operator's export.
    """
    graph = Graph()
    entities = CharterEntity.objects.filter(role__in=[*PERSON_ROLES, CharterEntity.Role.PLACE])
    relations = Relation.objects.all()
    if texts is not None:
        entities = entities.filter(image_text__in=texts)
        relations = relations.filter(image_text__in=texts)
    part = "image_text__item_image__item_part_id"
    entity_rows = list(entities.order_by("pk").values_list(part, "role", "name"))
    relation_rows = list(relations.order_by("pk").values_list(part, "subject", "predicate", "object"))

    part_ids = {row[0] for row in entity_rows} | {row[0] for row in relation_rows}
    parts = ItemPart.objects.filter(pk__in=part_ids).select_related("current_item__repository", "historical_item")
    for item_part in parts.prefetch_related("historical_item__catalogue_numbers__catalogue"):
        graph.add_node(f"charter:{item_part.pk}", item_part.display_label(), "charter", record=item_part.pk)

    for part_id, role, name in entity_rows:
        charter = f"charter:{part_id}"
        if role == CharterEntity.Role.PLACE:
            graph.add_node(_place_key(name), name, "place")
            graph.add_edge(charter, _place_key(name), "located_at")
        else:
            graph.add_node(_person_key(name), name, "person")
            graph.add_edge(_person_key(name), charter, role)

    for part_id, subject, predicate, obj in relation_rows:
        graph.add_node(_person_key(subject), subject, "person")
        if predicate == Relation.Predicate.LOCATED_AT:
            target = _place_key(obj)
            graph.add_node(target, obj, "place")
        else:
            target = _person_key(obj)
            graph.add_node(target, obj, "person")
        graph.add_edge(_person_key(subject), target, predicate, charter=f"charter:{part_id}")

    # The DigiPal import filed every unattributed hand under one placeholder
    # scribe at pk -1. Drawn, it would join hundreds of charters through
    # someone who never existed.
    attributions = (
        Hand.objects.filter(item_part_id__in=part_ids, scribe_id__gte=1)
        .order_by("scribe_id", "item_part_id")
        .values_list("scribe_id", "scribe__name", "item_part_id")
        .distinct()
    )
    for scribe_id, scribe_name, part_id in attributions:
        graph.add_node(f"scribe:{scribe_id}", scribe_name, "scribe", record=scribe_id)
        graph.add_edge(f"scribe:{scribe_id}", f"charter:{part_id}", "scribe")

    return graph


def to_json(graph: Graph) -> dict[str, list[dict]]:
    """The graph as the site's network view reads it."""
    return {
        "nodes": [{"id": key, **node} for key, node in sorted(graph.nodes.items())],
        "edges": graph.edges,
    }


def to_gexf(graph: Graph) -> str:
    """Serialise to GEXF 1.3, for Gephi and the rest."""
    root = ET.Element("gexf", {"xmlns": GEXF_NS, "xmlns:viz": VIZ_NS, "version": "1.3"})
    meta = ET.SubElement(root, "meta")
    ET.SubElement(meta, "creator").text = "Archetype — Models of Authority"
    ET.SubElement(
        meta, "description"
    ).text = "Witness, grantor and scribe network from expert-approved diplomatic entities."

    graph_el = ET.SubElement(root, "graph", {"mode": "static", "defaultedgetype": "directed"})

    attributes = ET.SubElement(graph_el, "attributes", {"class": "node"})
    ET.SubElement(attributes, "attribute", {"id": "kind", "title": "kind", "type": "string"})
    ET.SubElement(attributes, "attribute", {"id": "record", "title": "record", "type": "integer"})
    edge_attributes = ET.SubElement(graph_el, "attributes", {"class": "edge"})
    ET.SubElement(edge_attributes, "attribute", {"id": "charter", "title": "charter", "type": "string"})

    nodes_el = ET.SubElement(graph_el, "nodes")
    for key, node in sorted(graph.nodes.items()):
        node_el = ET.SubElement(nodes_el, "node", {"id": key, "label": node["label"]})
        values = ET.SubElement(node_el, "attvalues")
        ET.SubElement(values, "attvalue", {"for": "kind", "value": node["kind"]})
        if node["record"] is not None:
            ET.SubElement(values, "attvalue", {"for": "record", "value": str(node["record"])})

    edges_el = ET.SubElement(graph_el, "edges")
    for index, edge in enumerate(graph.edges):
        edge_el = ET.SubElement(
            edges_el,
            "edge",
            {
                "id": str(index),
                "source": edge["source"],
                "target": edge["target"],
                "label": edge["relation"],
            },
        )
        if edge["charter"]:
            values = ET.SubElement(edge_el, "attvalues")
            ET.SubElement(values, "attvalue", {"for": "charter", "value": edge["charter"]})

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")

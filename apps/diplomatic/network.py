"""W2.3 — the witness and scribe network, and its GEXF export.

Built from approved entities and relations plus the hand groupings the corpus
already has. No model runs here: the network is a view of what humans accepted,
which is why it can be built and checked today while the pipelines that feed it
wait on a key.

GEXF because the roadmap asks for it by name — the point is that the graph is
usable in Gephi and the standard network-analysis tools, not only in a view of
ours. A network you cannot take away is a picture, not data.
"""

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from apps.diplomatic.models import CharterEntity, Relation

GEXF_NS = "http://gexf.net/1.3"
VIZ_NS = "http://gexf.net/1.3/viz"


@dataclass
class Graph:
    """People, places and charters, and what connects them."""

    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)

    def add_node(self, key: str, label: str, kind: str) -> None:
        self.nodes.setdefault(key, {"label": label, "kind": kind})

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


def build() -> Graph:
    """The network as it stands, from approved rows only."""
    graph = Graph()

    for entity in CharterEntity.objects.select_related("image_text").all():
        charter = f"charter:{entity.image_text_id}"
        graph.add_node(charter, f"Charter {entity.image_text_id}", "charter")

        if entity.role in (CharterEntity.Role.GRANTER, CharterEntity.Role.BENEFICIARY, CharterEntity.Role.WITNESS):
            key = _person_key(entity.name)
            graph.add_node(key, entity.name, "person")
            graph.add_edge(key, charter, entity.role)
        elif entity.role == CharterEntity.Role.PLACE:
            key = f"place:{entity.name.strip().lower()}"
            graph.add_node(key, entity.name, "place")
            graph.add_edge(charter, key, "located_at")

    for relation in Relation.objects.all():
        subject = _person_key(relation.subject)
        obj = _person_key(relation.object)
        graph.add_node(subject, relation.subject, "person")
        graph.add_node(obj, relation.object, "person")
        graph.add_edge(subject, obj, relation.predicate, charter=str(relation.image_text_id))

    return graph


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
    edge_attributes = ET.SubElement(graph_el, "attributes", {"class": "edge"})
    ET.SubElement(edge_attributes, "attribute", {"id": "charter", "title": "charter", "type": "string"})

    nodes_el = ET.SubElement(graph_el, "nodes")
    for key, node in sorted(graph.nodes.items()):
        node_el = ET.SubElement(nodes_el, "node", {"id": key, "label": node["label"]})
        values = ET.SubElement(node_el, "attvalues")
        ET.SubElement(values, "attvalue", {"for": "kind", "value": node["kind"]})

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

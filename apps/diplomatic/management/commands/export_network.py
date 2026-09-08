"""W2.3 — write the witness/scribe network to GEXF.

No model is involved: the network is a view of approved rows, which is why it
can be produced and checked today, before any pipeline has run. On an empty
corpus it writes an empty graph rather than failing — that is the honest
answer at this stage of the programme, and an operator can see it.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

from apps.diplomatic import network


class Command(BaseCommand):
    help = "Export the approved witness/grantor/scribe network as GEXF."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--out", default="network.gexf", help="Destination path.")

    def handle(self, *args: Any, **options: Any) -> None:
        graph = network.build()
        path = Path(options["out"])
        path.write_text(network.to_gexf(graph), encoding="utf-8")

        people = sum(1 for node in graph.nodes.values() if node["kind"] == "person")
        self.stdout.write(
            f"{len(graph.nodes)} nodes ({people} people), {len(graph.edges)} edges, "
            f"density {graph.density:.4f} → {path}"
        )
        if not graph.edges:
            self.stdout.write(
                self.style.WARNING(
                    "The network is empty: no entity or relation has been approved yet. "
                    "Run the W2.1/W3.3 pipelines and review their proposals first."
                )
            )

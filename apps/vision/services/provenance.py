"""What a model's accepted proposal became, for the ledger.

The ledger answers "which call produced this record?". The annotations app may
not import `ml`, so it says when a proposal is accepted and this records it.
"""

from typing import Any

from apps.ml.services import ledger


def record_accepted_graph(sender: Any, proposal: Any, graph: Any, **kwargs: Any) -> None:
    if proposal.ml_job_id:
        ledger.attach_targets(proposal.ml_job, [("graph", graph.pk)])

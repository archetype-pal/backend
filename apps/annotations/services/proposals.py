"""The annotation write gate (AI programme W0.5).

Machine output enters as a `GraphProposal` and can leave only one way: a human
calls `accept`, and a `Graph` is created with that human recorded as the actor.
There is no other path from a proposal to the canonical record, and nothing in
the ML app can reach this module — it does not import `apps.annotations`, and
the boundary checker keeps it that way.

The annotation-QC track's `GraphReview` is not this. That reviews rows which are
already canonical and explicitly guarantees annotation writes are never blocked;
this blocks them. The two compose — a gate in front, an audit behind — and W0.5
owns the gate.
"""

from typing import cast

from django.db import transaction
from django.utils import timezone

from apps.annotations.models import Graph, GraphProposal
from apps.common.audit import audit_actor


class ProposalError(Exception):
    """A proposal cannot be decided as asked."""


def propose(
    *,
    item_image_id: int,
    annotation: dict,
    allograph_id: int | None = None,
    hand_id: int | None = None,
    annotation_type: str = cast(str, Graph.AnnotationType.IMAGE),
    confidence: float | None = None,
    ml_job_id: int | None = None,
) -> GraphProposal:
    """Record a candidate annotation. Creates no `Graph`."""
    return cast(
        GraphProposal,
        GraphProposal.objects.create(
            item_image_id=item_image_id,
            annotation=annotation,
            allograph_id=allograph_id,
            hand_id=hand_id,
            annotation_type=annotation_type,
            confidence=confidence,
            ml_job_id=ml_job_id,
            status=GraphProposal.Status.PENDING,
        ),
    )


@transaction.atomic
def accept(proposal: GraphProposal, *, reviewer) -> Graph:
    """Promote *proposal* to a real annotation, on a human's authority.

    The reviewer is required, not optional: an accepted proposal with no actor
    would be machine output in the canonical record wearing a human's clothes,
    which is the one outcome this whole mechanism exists to prevent.
    """
    if not getattr(reviewer, "is_authenticated", False):
        raise ProposalError("Accepting a proposal requires an authenticated reviewer.")

    # Lock before deciding. Without this, two concurrent accepts — a
    # double-clicked button is enough — both read `pending` from their own
    # in-memory copy and both create a Graph, minting two canonical annotations
    # from one human decision and leaving one of them attached to nothing.
    locked = GraphProposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != GraphProposal.Status.PENDING:
        raise ProposalError(f"Proposal {proposal.pk} is already {locked.status}.")
    # `Graph` requires both for IMAGE rows (see its check constraint); catching
    # it here gives the reviewer a reason instead of an IntegrityError.
    if proposal.annotation_type == Graph.AnnotationType.IMAGE and not (proposal.allograph_id and proposal.hand_id):
        raise ProposalError("An image annotation needs both an allograph and a hand before it can be accepted.")

    # Bound *around* the create, not assigned after it: the audit signal fires
    # inside `create()`, so setting an attribute afterwards records nothing and
    # the canonical row's trail would say nobody made it. This is the mechanism
    # `AuditActorMixin` uses for the same reason.
    with audit_actor(reviewer):
        graph: Graph = Graph.objects.create(
            item_image_id=proposal.item_image_id,
            annotation=proposal.annotation,
            allograph_id=proposal.allograph_id,
            hand_id=proposal.hand_id,
            annotation_type=proposal.annotation_type,
        )

    proposal.status = GraphProposal.Status.ACCEPTED
    proposal.reviewer = reviewer
    proposal.reviewed = timezone.now()
    proposal.accepted_graph = graph
    proposal.save(update_fields=["status", "reviewer", "reviewed", "accepted_graph"])
    return graph


def reject(proposal: GraphProposal, *, reviewer, reason: str = "") -> GraphProposal:
    """Close *proposal* without creating anything."""
    if not getattr(reviewer, "is_authenticated", False):
        raise ProposalError("Rejecting a proposal requires an authenticated reviewer.")
    if proposal.status != GraphProposal.Status.PENDING:
        raise ProposalError(f"Proposal {proposal.pk} is already {proposal.status}.")

    proposal.status = GraphProposal.Status.REJECTED
    proposal.reviewer = reviewer
    proposal.reviewed = timezone.now()
    proposal.reason = reason[:2000]
    proposal.save(update_fields=["status", "reviewer", "reviewed", "reason"])
    return proposal


def queue_depth() -> int:
    """Pending proposals awaiting a human.

    The number the programme's reviewer-capacity stop rule is measured against:
    proposal generation pauses when this outruns the people reviewing it.
    """
    return int(GraphProposal.objects.filter(status=GraphProposal.Status.PENDING).count())

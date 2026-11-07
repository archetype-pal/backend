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
from django.dispatch import Signal
from django.utils import timezone

from apps.annotations.models import Graph, GraphProposal
from apps.common.audit import audit_actor


class ProposalError(Exception):
    """A proposal cannot be decided as asked."""


# Sent with `proposal` and `graph`, so the ledger can record what a call became.
proposal_accepted = Signal()


def propose(
    *,
    item_image_id: int,
    annotation: dict,
    allograph_id: int | None = None,
    hand_id: int | None = None,
    annotation_type: str = cast(str, Graph.AnnotationType.IMAGE),
    confidence: float | None = None,
    ml_job_id: int | None = None,
    requested_by=None,
    description: dict | None = None,
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
            requested_by=requested_by,
            description=description or {},
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
    # The graph is made from the locked row, not the caller's copy: a correction
    # committed while this waited for the lock is what the reviewer accepts.
    # `Graph` requires both for IMAGE rows (see its check constraint); catching
    # it here gives the reviewer a reason instead of an IntegrityError.
    if locked.annotation_type == Graph.AnnotationType.IMAGE and not (locked.allograph_id and locked.hand_id):
        raise ProposalError("An image annotation needs both an allograph and a hand before it can be accepted.")

    # Bound *around* the create, not assigned after it: the audit signal fires
    # inside `create()`, so setting an attribute afterwards records nothing and
    # the canonical row's trail would say nobody made it. This is the mechanism
    # `AuditActorMixin` uses for the same reason.
    with audit_actor(reviewer):
        graph: Graph = Graph.objects.create(
            item_image_id=locked.item_image_id,
            annotation=locked.annotation,
            allograph_id=locked.allograph_id,
            hand_id=locked.hand_id,
            annotation_type=locked.annotation_type,
        )

    proposal.status = GraphProposal.Status.ACCEPTED
    proposal.reviewer = reviewer
    proposal.reviewed = timezone.now()
    proposal.accepted_graph = graph
    proposal.save(update_fields=["status", "reviewer", "reviewed", "accepted_graph"])
    proposal_accepted.send(sender=GraphProposal, proposal=proposal, graph=graph)
    return graph


@transaction.atomic
def correct(
    proposal: GraphProposal,
    *,
    reviewer,
    allograph_id: int | None = None,
    hand_id: int | None = None,
    annotation: dict | None = None,
) -> GraphProposal:
    """Change what a pending proposal says, leaving it pending.

    Only what is given changes; nothing can be cleared, since a correction names
    the right value. It creates no `Graph`: the corrected proposal stays in the
    queue until someone accepts or rejects it. What the model filed is kept on
    the first correction, so the queue can show it and a model's acceptance
    rate counts a corrected letter as the model's miss.
    """
    if not getattr(reviewer, "is_authenticated", False):
        raise ProposalError("Correcting a proposal requires an authenticated reviewer.")
    # Locked for the reason `accept` is: a correction must not land on a
    # proposal that was decided while it was being made.
    locked: GraphProposal = GraphProposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != GraphProposal.Status.PENDING:
        raise ProposalError(f"Proposal {proposal.pk} is already {locked.status}.")

    asked = {"allograph_id": allograph_id, "hand_id": hand_id, "annotation": annotation}
    changes = {field: value for field, value in asked.items() if value is not None and value != getattr(locked, field)}
    if not changes:
        return locked

    if locked.proposed is None:
        locked.proposed = {"annotation": locked.annotation, "allograph": locked.allograph_id, "hand": locked.hand_id}
    for field, value in changes.items():
        setattr(locked, field, value)
    locked.corrected_by = reviewer
    locked.corrected = timezone.now()
    changed = [field.removesuffix("_id") for field in changes]
    locked.save(update_fields=[*changed, "proposed", "corrected_by", "corrected"])
    return locked


@transaction.atomic
def reject(proposal: GraphProposal, *, reviewer, reason: str = "") -> GraphProposal:
    """Close *proposal* without creating anything."""
    if not getattr(reviewer, "is_authenticated", False):
        raise ProposalError("Rejecting a proposal requires an authenticated reviewer.")
    # Locked for the reason `accept` is. Checking the caller's copy instead lets
    # a reject that read `pending` before a concurrent accept committed write
    # `rejected` over it, leaving a canonical Graph whose proposal says no one
    # accepted it.
    locked = GraphProposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != GraphProposal.Status.PENDING:
        raise ProposalError(f"Proposal {proposal.pk} is already {locked.status}.")

    proposal.status = GraphProposal.Status.REJECTED
    proposal.reviewer = reviewer
    proposal.reviewed = timezone.now()
    proposal.reason = reason[:2000]
    proposal.save(update_fields=["status", "reviewer", "reviewed", "reason"])
    return proposal


@transaction.atomic
def adopt(proposal_id: int, *, graph: Graph, reviewer) -> GraphProposal | None:
    """Record that *reviewer*'s saved annotation came from the proposal they asked for (W3.5).

    The person made the `Graph` through the viewer's own save, under their name;
    this only closes the proposal against it. What differs from what the model
    filed is kept as a correction, so a model is judged by what it proposed. A
    proposal that is not theirs, not pending or on another page is left alone:
    it must not stop someone's annotation from saving.
    """
    locked: GraphProposal | None = (
        GraphProposal.objects.select_for_update()
        .filter(
            pk=proposal_id,
            status=GraphProposal.Status.PENDING,
            requested_by=reviewer,
            item_image_id=graph.item_image_id,
        )
        .first()
    )
    if locked is None:
        return None
    now = timezone.now()
    if (locked.allograph_id, locked.hand_id, locked.annotation) != (
        graph.allograph_id,
        graph.hand_id,
        graph.annotation,
    ):
        locked.proposed = {"annotation": locked.annotation, "allograph": locked.allograph_id, "hand": locked.hand_id}
        locked.allograph_id, locked.hand_id, locked.annotation = graph.allograph_id, graph.hand_id, graph.annotation
        locked.corrected_by, locked.corrected = reviewer, now
    locked.status = GraphProposal.Status.ACCEPTED
    locked.reviewer, locked.reviewed, locked.accepted_graph = reviewer, now, graph
    locked.save()
    proposal_accepted.send(sender=GraphProposal, proposal=locked, graph=graph)
    return locked


def close_abandoned(*, before) -> int:
    """Close suggestions from the viewer nobody settled: the page was left, or the tab closed."""
    return int(
        GraphProposal.objects.filter(
            status=GraphProposal.Status.PENDING, requested_by__isnull=False, created__lt=before
        ).update(status=GraphProposal.Status.REJECTED, reason="Abandoned: left undecided in the viewer.")
    )


def queue_depth() -> int:
    """Pending proposals awaiting a reviewer.

    The number the programme's reviewer-capacity stop rule is measured against:
    proposal generation pauses when this outruns the people reviewing it. A
    proposal someone asked for in the viewer is theirs to settle, so it is not counted.
    """
    return int(GraphProposal.objects.filter(status=GraphProposal.Status.PENDING, requested_by__isnull=True).count())

"""The annotation write gate — AI programme W0.5.

C1's guarantee is that no AI output reaches the canonical record without a human
deciding. Until this existed the guarantee held for charter texts and not for
annotations, which is the highest-volume thing the programme produces. These
tests pin the guarantee in the direction it must fail: a proposal is not an
annotation, and only a named human can make it one.
"""

import pytest

from apps.annotations.models import Graph, GraphProposal
from apps.annotations.services import proposals
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.tests.factories import MLJobFactory
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory

BOX = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [9, 0], [9, 9], [0, 9], [0, 0]]]}}


@pytest.fixture
def proposal(db):
    return proposals.propose(
        item_image_id=ItemImageFactory().pk,
        annotation=BOX,
        allograph_id=AllographFactory().pk,
        hand_id=HandFactory().pk,
        ml_job_id=MLJobFactory().pk,
    )


@pytest.mark.django_db
class TestTheGate:
    def test_a_proposal_is_not_an_annotation(self, proposal):
        """The canonical table never contains an unreviewed row — structurally."""
        assert proposal.status == GraphProposal.Status.PENDING
        assert Graph.objects.count() == 0
        assert Graph.all_objects.count() == 0

    def test_accepting_is_the_only_path_across(self, proposal, django_user_model):
        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")

        graph = proposals.accept(proposal, reviewer=reviewer)

        proposal.refresh_from_db()
        assert Graph.objects.count() == 1
        assert proposal.status == GraphProposal.Status.ACCEPTED
        assert proposal.accepted_graph_id == graph.pk
        assert proposal.reviewer == reviewer
        assert proposal.reviewed is not None

    def test_rejecting_creates_nothing(self, proposal, django_user_model):
        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")

        proposals.reject(proposal, reviewer=reviewer, reason="box is off the letter")

        proposal.refresh_from_db()
        assert Graph.objects.count() == 0
        assert proposal.status == GraphProposal.Status.REJECTED
        assert proposal.reason == "box is off the letter"

    def test_an_anonymous_caller_cannot_accept(self, proposal):
        """An accepted proposal with no actor is machine output in human clothes."""

        class Anonymous:
            is_authenticated = False

        with pytest.raises(proposals.ProposalError, match="authenticated reviewer"):
            proposals.accept(proposal, reviewer=Anonymous())

        assert Graph.objects.count() == 0

    def test_a_decision_cannot_be_taken_twice(self, proposal, django_user_model):
        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")
        proposals.accept(proposal, reviewer=reviewer)

        with pytest.raises(proposals.ProposalError, match="already accepted"):
            proposals.accept(proposal, reviewer=reviewer)

        assert Graph.objects.count() == 1

    def test_an_incomplete_image_proposal_is_refused_with_a_reason(self, django_user_model):
        """`Graph`'s check constraint requires both; say so rather than 500."""
        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")
        incomplete = proposals.propose(item_image_id=ItemImageFactory().pk, annotation=BOX)

        with pytest.raises(proposals.ProposalError, match="allograph and a hand"):
            proposals.accept(incomplete, reviewer=reviewer)

        assert Graph.objects.count() == 0


@pytest.mark.django_db
class TestAuditTrail:
    def test_the_reviewer_reaches_the_canonical_row_s_audit_trail(self, proposal, django_user_model):
        """`EditEvent` is the only place a Graph's author exists. Setting the
        actor *after* create() records nothing, because the signal has already
        fired — and every earlier test passed through the view, which binds the
        actor separately."""
        from apps.common.models import EditEvent

        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")

        graph = proposals.accept(proposal, reviewer=reviewer)

        event = EditEvent.objects.get(target_type="graph", target_id=graph.pk, action=EditEvent.Action.CREATED)
        assert event.actor == reviewer


@pytest.mark.django_db
class TestProvenance:
    def test_a_proposal_stays_attributable_to_the_inference(self, proposal):
        assert proposal.ml_job_id is not None

    def test_the_ledger_row_cannot_be_deleted_out_from_under_it(self, proposal):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            proposal.ml_job.delete()


@pytest.mark.django_db
class TestQueueDepth:
    def test_counts_only_undecided_proposals(self, proposal, django_user_model):
        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")
        assert proposals.queue_depth() == 1

        proposals.reject(proposal, reviewer=reviewer)

        assert proposals.queue_depth() == 0


@pytest.mark.django_db
class TestReviewQueueAPI:
    URL = "/api/v1/management/annotations/proposals/"

    def test_anonymous_and_ordinary_users_are_refused(self, api_client, authenticated_client):
        assert api_client.get(self.URL).status_code in (401, 403)
        assert authenticated_client.get(self.URL).status_code == 403

    def test_a_superuser_sees_the_queue(self, management_client, proposal):
        body = management_client.get(self.URL).json()
        results = body["results"] if isinstance(body, dict) else body

        assert [row["id"] for row in results] == [proposal.pk]

    def test_a_proposal_is_not_editable_over_http(self, management_client, proposal):
        response = management_client.patch(f"{self.URL}{proposal.pk}/", {"status": "accepted"}, format="json")

        assert response.status_code == 405
        proposal.refresh_from_db()
        assert proposal.status == GraphProposal.Status.PENDING

    def test_accepting_creates_the_annotation_and_records_the_reviewer(self, management_client, proposal):
        response = management_client.post(f"{self.URL}{proposal.pk}/accept/", {}, format="json")

        assert response.status_code == 201, response.json()
        proposal.refresh_from_db()
        assert Graph.objects.filter(pk=response.json()["graph_id"]).exists()
        assert proposal.reviewer is not None

    def test_rejecting_records_the_reason(self, management_client, proposal):
        response = management_client.post(f"{self.URL}{proposal.pk}/reject/", {"reason": "spurious"}, format="json")

        assert response.status_code == 200
        proposal.refresh_from_db()
        assert proposal.status == GraphProposal.Status.REJECTED
        assert proposal.reason == "spurious"
        assert Graph.objects.count() == 0

    def test_deciding_twice_is_a_conflict_not_a_crash(self, management_client, proposal):
        management_client.post(f"{self.URL}{proposal.pk}/accept/", {}, format="json")

        response = management_client.post(f"{self.URL}{proposal.pk}/accept/", {}, format="json")

        assert response.status_code == 409
        assert Graph.objects.count() == 1

    def test_depth_reports_the_pending_count(self, management_client, proposal):
        assert management_client.get(f"{self.URL}depth/").json() == {"pending": 1}

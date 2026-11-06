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

    def test_a_stale_copy_cannot_reject_what_was_accepted(self, proposal, django_user_model):
        """Two reviewers open the same proposal; one accepts. The other's reject,
        holding a copy that still reads `pending`, must not overwrite the decision."""
        reviewer = django_user_model.objects.create_user(username="reviewer", password="x")
        stale = GraphProposal.objects.get(pk=proposal.pk)
        proposals.accept(proposal, reviewer=reviewer)

        with pytest.raises(proposals.ProposalError, match="already accepted"):
            proposals.reject(stale, reviewer=reviewer)

        proposal.refresh_from_db()
        assert proposal.status == GraphProposal.Status.ACCEPTED
        assert proposal.accepted_graph_id is not None

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

    def test_lists_the_newest_request_first_and_the_likeliest_of_each_first(self, management_client):
        image, allograph, hand = ItemImageFactory(), AllographFactory(), HandFactory()
        older, newer = MLJobFactory(), MLJobFactory()

        def filed(job, confidence):
            return proposals.propose(
                item_image_id=image.pk,
                annotation=BOX,
                allograph_id=allograph.pk,
                hand_id=hand.pk,
                confidence=confidence,
                ml_job_id=job.pk if job else None,
            ).pk

        # Each request files its best proposal first, as a model does.
        old_best, old_worst = filed(older, 0.9), filed(older, 0.4)
        unattributed = filed(None, 0.99)
        new_best, new_unscored, new_worst = filed(newer, 0.8), filed(newer, None), filed(newer, 0.3)
        # Equally likely, the later filed comes first, as the queue always had it.
        tied_first, tied_second = filed(newer, 0.5), filed(newer, 0.5)

        body = management_client.get(self.URL).json()
        results = body["results"] if isinstance(body, dict) else body

        assert [row["id"] for row in results] == [
            new_best,
            tied_second,
            tied_first,
            new_worst,
            new_unscored,
            old_best,
            old_worst,
            unattributed,
        ]

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


@pytest.mark.django_db
class TestReviewQueueRows:
    """A row carries what the reviewer decides by, without another request."""

    URL = "/api/v1/management/annotations/proposals/"

    def _row(self, client, pk):
        return client.get(f"{self.URL}{pk}/").json()

    def test_a_row_names_the_letter_the_hand_the_page_and_the_model(self, management_client, proposal):
        row = self._row(management_client, proposal.pk)

        assert row["allograph_name"] == proposal.allograph.name
        assert row["hand_name"] == proposal.hand.name
        assert row["image_display"] == str(proposal.item_image)
        assert row["historical_item"] == proposal.item_image.item_part.historical_item_id
        assert row["model_name"] == proposal.ml_job.model_name

    def test_a_row_carries_the_page_s_iiif_info_url(self, management_client, proposal):
        """The queue crops the proposed box from this; a bare id would cost a request per row."""
        row = self._row(management_client, proposal.pk)

        assert row["image_iiif"].endswith("/info.json")

    def test_a_proposal_with_no_hand_or_ledger_row_still_reads(self, management_client):
        """A page whose part has no hand yields exactly this, and must show rather than 500."""
        bare = proposals.propose(item_image_id=ItemImageFactory().pk, annotation=BOX)

        row = self._row(management_client, bare.pk)

        assert row["hand_name"] is None
        assert row["allograph_name"] is None
        assert row["model_name"] == ""

    def test_the_list_s_query_count_does_not_grow_with_its_rows(self, management_client):
        from apps.common.tests.query_counts import assert_query_count_constant

        def add(n):
            for _ in range(n):
                proposals.propose(
                    item_image_id=ItemImageFactory().pk,
                    annotation=BOX,
                    allograph_id=AllographFactory().pk,
                    hand_id=HandFactory().pk,
                    ml_job_id=MLJobFactory().pk,
                )

        assert_query_count_constant(management_client, self.URL, add)


def _polygon(*rings):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": list(rings)}}


def _ring(left, lower, right, upper):
    return _polygon([[left, lower], [right, lower], [right, upper], [left, upper], [left, lower]])


@pytest.mark.django_db
class TestCorrection:
    """A reviewer may correct a pending proposal; it stays a proposal until decided."""

    @pytest.fixture
    def reviewer(self, django_user_model):
        return django_user_model.objects.create_user(username="reviewer", password="x")

    def test_a_correction_changes_the_proposal_and_keeps_what_the_model_filed(self, proposal, reviewer):
        filed_allograph, filed_box = proposal.allograph_id, proposal.annotation
        right_letter, right_box = AllographFactory(), _ring(2, 2, 8, 9)

        proposals.correct(proposal, reviewer=reviewer, allograph_id=right_letter.pk, annotation=right_box)

        proposal.refresh_from_db()
        assert proposal.status == GraphProposal.Status.PENDING
        assert (proposal.allograph_id, proposal.annotation) == (right_letter.pk, right_box)
        assert proposal.proposed == {"annotation": filed_box, "allograph": filed_allograph, "hand": proposal.hand_id}
        assert proposal.corrected_by == reviewer
        assert proposal.corrected is not None
        assert Graph.objects.count() == 0

    def test_a_second_correction_still_keeps_the_model_s_proposal(self, proposal, reviewer):
        filed = proposal.allograph_id
        proposals.correct(proposal, reviewer=reviewer, allograph_id=AllographFactory().pk)

        proposals.correct(proposal, reviewer=reviewer, allograph_id=AllographFactory().pk)

        proposal.refresh_from_db()
        assert proposal.proposed["allograph"] == filed

    def test_naming_what_it_already_says_is_no_correction(self, proposal, reviewer):
        proposals.correct(proposal, reviewer=reviewer, allograph_id=proposal.allograph_id)

        proposal.refresh_from_db()
        assert proposal.proposed is None
        assert proposal.corrected_by is None

    def test_a_decided_proposal_cannot_be_corrected(self, proposal, reviewer):
        proposals.reject(proposal, reviewer=reviewer)

        with pytest.raises(proposals.ProposalError, match="already rejected"):
            proposals.correct(proposal, reviewer=reviewer, allograph_id=AllographFactory().pk)

    def test_an_anonymous_caller_cannot_correct(self, proposal):
        class Anonymous:
            is_authenticated = False

        with pytest.raises(proposals.ProposalError, match="authenticated reviewer"):
            proposals.correct(proposal, reviewer=Anonymous(), allograph_id=AllographFactory().pk)

    def test_accepting_a_corrected_proposal_creates_the_corrected_annotation(self, reviewer):
        """A page with no hand recorded yields an unacceptable proposal until someone names one."""
        image = ItemImageFactory()
        incomplete = proposals.propose(item_image_id=image.pk, annotation=BOX, allograph_id=AllographFactory().pk)
        hand, box = HandFactory(item_part=image.item_part), _ring(1, 1, 7, 7)
        proposals.correct(incomplete, reviewer=reviewer, hand_id=hand.pk, annotation=box)

        graph = proposals.accept(incomplete, reviewer=reviewer)

        assert (graph.hand_id, graph.annotation) == (hand.pk, box)

    def test_an_accept_that_read_the_proposal_before_a_correction_accepts_the_correction(self, proposal, reviewer):
        stale = GraphProposal.objects.get(pk=proposal.pk)
        right_letter = AllographFactory()
        proposals.correct(proposal, reviewer=reviewer, allograph_id=right_letter.pk)

        graph = proposals.accept(stale, reviewer=reviewer)

        assert graph.allograph_id == right_letter.pk


@pytest.mark.django_db
class TestCorrectionAPI:
    URL = "/api/v1/management/annotations/proposals/"

    def _correct(self, client, proposal, body):
        return client.post(f"{self.URL}{proposal.pk}/correct/", body, format="json")

    def test_a_correction_answers_with_the_corrected_row(self, management_client, management_user, proposal):
        filed = proposal.allograph_id
        right_letter = AllographFactory()
        hand = HandFactory(item_part=proposal.item_image.item_part)
        box = _ring(3, 3, 9, 9)

        response = self._correct(
            management_client, proposal, {"allograph": right_letter.pk, "hand": hand.pk, "annotation": box}
        )

        assert response.status_code == 200, response.json()
        row = response.json()
        assert (row["allograph_name"], row["hand"], row["annotation"]) == (right_letter.name, hand.pk, box)
        assert row["status"] == "pending"
        assert row["proposed"]["allograph"] == filed
        assert row["corrected_by_username"] == management_user.username
        assert row["item_part"] == proposal.item_image.item_part_id

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({}, id="nothing to correct"),
            pytest.param({"allograph": None}, id="clearing the letter"),
            pytest.param({"annotation": [[0, 0], [9, 9]]}, id="not a feature"),
            pytest.param({"annotation": {**BOX, "geometry": {"type": "Point", "coordinates": [1, 1]}}}, id="a point"),
            pytest.param({"annotation": _polygon([[0, 0], [9, 0], [9, 9]])}, id="an open ring"),
            pytest.param(
                {"annotation": _polygon([[0, 0], [9, 0], [9, 9], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 1]])},
                id="a ring with a hole",
            ),
            pytest.param({"annotation": _ring(4, 0, 4, 9)}, id="no area"),
            pytest.param({"annotation": _ring(-3, 0, 4, 9)}, id="off the page"),
            pytest.param({"annotation": _polygon([[True, 0], [9, 0], [9, 9], [True, 0]])}, id="not numbers"),
        ],
    )
    def test_a_correction_that_cannot_be_the_proposal_s_is_refused(self, management_client, proposal, body):
        response = self._correct(management_client, proposal, body)

        assert response.status_code == 400
        proposal.refresh_from_db()
        assert proposal.proposed is None

    def test_a_hand_of_another_manuscript_is_refused(self, management_client, proposal):
        response = self._correct(management_client, proposal, {"hand": HandFactory().pk})

        assert response.status_code == 400
        assert "hand" in response.json()

    def test_correcting_a_decided_proposal_is_a_conflict(self, management_client, proposal):
        management_client.post(f"{self.URL}{proposal.pk}/accept/", {}, format="json")

        response = self._correct(management_client, proposal, {"allograph": AllographFactory().pk})

        assert response.status_code == 409


@pytest.mark.django_db
class TestWhatAProposalHoldsOnTo:
    def test_a_decided_proposal_does_not_keep_a_letter_or_a_hand_from_being_deleted(self):
        allograph, hand = AllographFactory(), HandFactory()
        proposal = proposals.propose(
            item_image_id=ItemImageFactory().pk, annotation={}, allograph_id=allograph.pk, hand_id=hand.pk
        )

        allograph.delete()
        hand.delete()

        proposal.refresh_from_db()
        assert (proposal.allograph_id, proposal.hand_id) == (None, None)

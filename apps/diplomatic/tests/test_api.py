"""The review gate over HTTP, and the public collections behind it."""

import pytest
from rest_framework.test import APIClient

from apps.diplomatic.models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation
from apps.manuscripts.tests.factories import ImageTextFactory
from apps.users.tests.factories import UserFactory


@pytest.fixture
def staff_client(db):
    user = UserFactory(is_staff=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def proposal(db):
    text = ImageTextFactory()
    return Proposal.objects.create(
        pipeline="W2.1",
        source_type="imagetext",
        source_id=text.pk,
        payload={"entities": [{"role": "witness", "name": "Walterus"}]},
    )


@pytest.mark.django_db
class TestProposalGate:
    def test_the_queue_is_closed_to_the_public(self, api_client, proposal):
        assert api_client.get("/api/v1/management/diplomatic-proposals/").status_code in (401, 403)

    def test_a_regular_user_cannot_read_the_queue(self, authenticated_client, proposal):
        assert authenticated_client.get("/api/v1/management/diplomatic-proposals/").status_code == 403

    def test_staff_can_read_and_filter_it(self, staff_client, proposal):
        client, _ = staff_client

        response = client.get("/api/v1/management/diplomatic-proposals/?pipeline=W2.1")

        assert response.status_code == 200
        assert response.data["count"] == 1

    def test_accepting_writes_the_records_against_the_reviewer(self, staff_client, proposal):
        client, user = staff_client

        response = client.post(f"/api/v1/management/diplomatic-proposals/{proposal.pk}/accept/")

        assert response.status_code == 200
        assert response.data == {"status": "accepted", "created": 1}
        assert CharterEntity.objects.get().name == "Walterus"
        proposal.refresh_from_db()
        assert proposal.reviewer == user

    def test_accepting_twice_is_a_conflict_not_a_second_record(self, staff_client, proposal):
        client, _ = staff_client
        client.post(f"/api/v1/management/diplomatic-proposals/{proposal.pk}/accept/")

        response = client.post(f"/api/v1/management/diplomatic-proposals/{proposal.pk}/accept/")

        assert response.status_code == 409
        assert CharterEntity.objects.count() == 1

    @pytest.mark.parametrize(
        ("pipeline", "payload"),
        [
            ("W2.1", {"entities": [{"role": "witness", "name": "Walterus"}]}),
            ("W2.2", {"formulae": [{"kind": "sanctio", "label": "Sciant", "excerpt": "Sciant"}]}),
            ("W2.4", {"translation": "Know all", "notes": ""}),
            ("W3.3", {"triples": [{"subject": "Walterus", "predicate": "witnessed_by", "object": "carta"}]}),
        ],
    )
    def test_a_proposal_whose_text_was_deleted_is_refused_not_a_500(self, staff_client, pipeline, payload):
        client, _ = staff_client
        text = ImageTextFactory()
        orphan = Proposal.objects.create(pipeline=pipeline, source_type="imagetext", source_id=text.pk, payload=payload)
        text_id = text.pk
        text.delete()

        response = client.post(f"/api/v1/management/diplomatic-proposals/{orphan.pk}/accept/")

        assert response.status_code == 409
        assert f"Text {text_id}" in response.data["detail"]
        orphan.refresh_from_db()
        assert orphan.status == Proposal.Status.PENDING
        assert CharterEntity.objects.count() == FormulaOccurrence.objects.count() == Relation.objects.count() == 0

    def test_a_proposal_whose_text_was_deleted_can_still_be_rejected(self, staff_client):
        client, _ = staff_client
        text = ImageTextFactory()
        orphan = Proposal.objects.create(
            pipeline="W2.1", source_type="imagetext", source_id=text.pk, payload={"entities": []}
        )
        text.delete()

        response = client.post(f"/api/v1/management/diplomatic-proposals/{orphan.pk}/reject/", {}, format="json")

        assert response.status_code == 200
        orphan.refresh_from_db()
        assert orphan.status == Proposal.Status.REJECTED

    def test_rejecting_records_the_reason(self, staff_client, proposal):
        client, _ = staff_client

        response = client.post(
            f"/api/v1/management/diplomatic-proposals/{proposal.pk}/reject/",
            {"reason": "Misread."},
            format="json",
        )

        assert response.status_code == 200
        proposal.refresh_from_db()
        assert proposal.reason == "Misread."
        assert CharterEntity.objects.count() == 0

    def test_a_proposal_cannot_be_edited_before_it_is_accepted(self, staff_client, proposal):
        """A payload a reviewer could rewrite is a way to launder their own text
        through the ledger as a model's."""
        client, _ = staff_client

        response = client.put(
            f"/api/v1/management/diplomatic-proposals/{proposal.pk}/",
            {"payload": {"entities": []}},
            format="json",
        )

        assert response.status_code == 405


@pytest.mark.django_db
class TestReviewQueueRows:
    """A row carries what a reviewer decides by, without another request."""

    URL = "/api/v1/management/diplomatic-proposals/"

    def _proposal(self, text, pipeline="W2.1", payload=None, **extra):
        return Proposal.objects.create(
            pipeline=pipeline,
            source_type="imagetext",
            source_id=text.pk,
            payload=payload or {"entities": [{"role": "witness", "name": "Walterus"}]},
            **extra,
        )

    def test_a_listed_row_names_its_charter_its_model_and_its_payload(self, staff_client):
        from apps.ml.tests.factories import MLJobFactory

        client, _ = staff_client
        text = ImageTextFactory()
        proposal = self._proposal(text, ml_job=MLJobFactory(model_name="google/gemini-3-pro"))

        row = client.get(self.URL).data["results"][0]

        assert row["payload"] == proposal.payload
        assert row["model_name"] == "google/gemini-3-pro"
        item = text.item_image.item_part.historical_item
        assert row["source"] == {
            "image_text": text.pk,
            "type": "Transcription",
            "item_image": text.item_image_id,
            "item_part": text.item_image.item_part_id,
            "historical_item": item.pk,
            "label": str(text.item_image),
            "date": item.date.date,
        }

    def test_the_detail_carries_the_charter_text_as_the_model_read_it(self, staff_client):
        client, _ = staff_client
        text = ImageTextFactory(content='<p>Sciant <persName ref="#w">Walterus</persName>\n  filius Alani</p>')
        proposal = self._proposal(text)

        row = client.get(f"{self.URL}{proposal.pk}/").data

        assert row["source_text"] == "Sciant Walterus filius Alani"

    def test_a_proposal_whose_charter_is_gone_still_reads(self, staff_client):
        client, _ = staff_client
        text = ImageTextFactory()
        proposal = self._proposal(text)
        text.delete()

        listed = client.get(self.URL).data["results"][0]
        detail = client.get(f"{self.URL}{proposal.pk}/").data

        assert listed["source"] is None
        assert detail["source"] is None
        assert detail["source_text"] == ""

    def test_the_list_s_query_count_does_not_grow_with_its_rows(self, staff_client):
        from apps.common.tests.query_counts import assert_query_count_constant
        from apps.ml.tests.factories import MLJobFactory

        client, _ = staff_client

        def add(n):
            for _ in range(n):
                self._proposal(ImageTextFactory(), ml_job=MLJobFactory())

        assert_query_count_constant(client, self.URL, add)

    def test_depth_counts_pending_proposals_per_registered_pipeline(self, staff_client):
        client, user = staff_client
        text = ImageTextFactory()
        self._proposal(text)
        self._proposal(text)
        self._proposal(text, pipeline="W3.2", payload={"verdict": "inconsistent"})
        self._proposal(text, status=Proposal.Status.REJECTED, reviewer=user)

        body = client.get(f"{self.URL}depth/").data

        assert body["pending"] == 3
        assert body["by_pipeline"] == {"W2.1": 2, "W2.2": 0, "W2.4": 0, "W3.2": 1, "W3.3": 0}


@pytest.mark.django_db
class TestPublicCollections:
    def test_approved_entities_are_public(self, api_client):
        text = ImageTextFactory()
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name="Walterus")

        response = api_client.get("/api/v1/diplomatic/entities/?role=witness")

        assert response.status_code == 200
        assert response.data["results"][0]["name"] == "Walterus"

    def test_formulae_list_their_occurrences(self, api_client):
        text = ImageTextFactory()
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="anathema", exemplar="a")
        FormulaOccurrence.objects.create(formula=formula, image_text=text, excerpt="a")

        response = api_client.get(f"/api/v1/diplomatic/formulae/{formula.pk}/")

        assert response.data["occurrence_count"] == 1
        assert response.data["occurrences"][0]["image_text"] == text.pk

    def test_relations_are_public_and_filterable(self, api_client):
        text = ImageTextFactory()
        Relation.objects.create(image_text=text, subject="a", predicate=Relation.Predicate.WITNESSED_BY, object="b")

        response = api_client.get("/api/v1/diplomatic/relations/?predicate=witnessed_by")

        assert response.data["count"] == 1

    def test_the_public_collections_are_read_only(self, management_client):
        response = management_client.post(
            "/api/v1/diplomatic/entities/", {"role": "witness", "name": "x"}, format="json"
        )

        assert response.status_code == 405

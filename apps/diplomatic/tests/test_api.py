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

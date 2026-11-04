"""The review gate over HTTP, and the public collections behind it."""

import pytest
from rest_framework.test import APIClient

from apps.diplomatic.models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation
from apps.manuscripts.models import ImageText
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
        text = ImageTextFactory(status=ImageText.Status.LIVE)
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name="Walterus")

        response = api_client.get("/api/v1/diplomatic/entities/?role=witness")

        assert response.status_code == 200
        assert response.data["results"][0]["name"] == "Walterus"

    def test_formulae_list_their_occurrences(self, api_client):
        text = ImageTextFactory(status=ImageText.Status.LIVE)
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="anathema", exemplar="a")
        FormulaOccurrence.objects.create(formula=formula, image_text=text, excerpt="a")

        response = api_client.get(f"/api/v1/diplomatic/formulae/{formula.pk}/")

        assert response.data["occurrence_count"] == 1
        assert response.data["occurrences"][0]["image_text"] == text.pk

    def test_relations_are_public_and_filterable(self, api_client):
        text = ImageTextFactory(status=ImageText.Status.LIVE)
        Relation.objects.create(image_text=text, subject="a", predicate=Relation.Predicate.WITNESSED_BY, object="b")

        response = api_client.get("/api/v1/diplomatic/relations/?predicate=witnessed_by")

        assert response.data["count"] == 1

    def test_the_public_collections_are_read_only(self, management_client):
        response = management_client.post(
            "/api/v1/diplomatic/entities/", {"role": "witness", "name": "x"}, format="json"
        )

        assert response.status_code == 405


@pytest.mark.django_db
class TestPublicCollectionsHideDrafts:
    """What came from a text the public cannot open stays where that text is."""

    @pytest.fixture
    def texts(self, db):
        return ImageTextFactory(status=ImageText.Status.REVIEWED), ImageTextFactory(status=ImageText.Status.DRAFT)

    def test_entities_from_a_draft_are_not_public(self, api_client, texts):
        published, draft = texts
        CharterEntity.objects.create(image_text=published, role=CharterEntity.Role.WITNESS, name="Walterus")
        CharterEntity.objects.create(image_text=draft, role=CharterEntity.Role.WITNESS, name="Secretus")

        names = [row["name"] for row in api_client.get("/api/v1/diplomatic/entities/").data["results"]]

        assert names == ["Walterus"]

    def test_relations_from_a_draft_are_not_public(self, api_client, texts):
        published, draft = texts
        Relation.objects.create(
            image_text=published, subject="a", predicate=Relation.Predicate.WITNESSED_BY, object="b"
        )
        Relation.objects.create(image_text=draft, subject="c", predicate=Relation.Predicate.WITNESSED_BY, object="d")

        subjects = [row["subject"] for row in api_client.get("/api/v1/diplomatic/relations/").data["results"]]

        assert subjects == ["a"]

    def test_a_formula_lists_only_its_published_occurrences(self, api_client, texts):
        published, draft = texts
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="anathema", exemplar="anathema sit")
        FormulaOccurrence.objects.create(formula=formula, image_text=published, excerpt="anathema sit")
        FormulaOccurrence.objects.create(formula=formula, image_text=draft, excerpt="the draft's words")

        row = api_client.get("/api/v1/diplomatic/formulae/").data["results"][0]

        assert row["occurrence_count"] == 1
        assert [occurrence["excerpt"] for occurrence in row["occurrences"]] == ["anathema sit"]

    def test_a_formula_found_only_in_drafts_is_not_listed(self, api_client, texts):
        _, draft = texts
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="hidden", exemplar="the draft's words")
        FormulaOccurrence.objects.create(formula=formula, image_text=draft, excerpt="the draft's words")

        assert api_client.get("/api/v1/diplomatic/formulae/").data["count"] == 0
        assert api_client.get(f"/api/v1/diplomatic/formulae/{formula.pk}/").status_code == 404

    def test_a_formula_used_twice_by_published_texts_is_listed_once(self, api_client, texts):
        published, _ = texts
        other = ImageTextFactory(status=ImageText.Status.LIVE)
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="anathema", exemplar="a")
        FormulaOccurrence.objects.create(formula=formula, image_text=published, excerpt="a")
        FormulaOccurrence.objects.create(formula=formula, image_text=other, excerpt="a")

        response = api_client.get("/api/v1/diplomatic/formulae/")

        assert response.data["count"] == 1
        assert response.data["results"][0]["occurrence_count"] == 2

    def test_staff_see_records_from_drafts(self, staff_client, texts):
        client, _ = staff_client
        _, draft = texts
        CharterEntity.objects.create(image_text=draft, role=CharterEntity.Role.WITNESS, name="Secretus")

        assert client.get("/api/v1/diplomatic/entities/").data["count"] == 1


def _published(**kwargs):
    return ImageTextFactory(status=ImageText.Status.LIVE, **kwargs)


def _charter_of(text):
    part = text.item_image.item_part
    return {
        "image_text": text.pk,
        "type": "Transcription",
        "item_image": text.item_image_id,
        "item_part": part.pk,
        "locus": text.item_image.locus,
        "shelfmark": part.current_item.shelfmark,
        "repository": part.current_item.repository.name,
        "date": part.historical_item.date.date,
    }


@pytest.mark.django_db
class TestPublicRecordsNameTheirCharter:
    def test_an_entity_names_its_charter_and_how_to_open_it(self, api_client):
        text = _published()
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name="Walterus")

        row = api_client.get("/api/v1/diplomatic/entities/").data["results"][0]

        assert row["charter"] == _charter_of(text)

    def test_a_formula_occurrence_names_its_charter(self, api_client):
        text = _published()
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="anathema", exemplar="a")
        FormulaOccurrence.objects.create(formula=formula, image_text=text, excerpt="anathema sit")

        occurrence = api_client.get("/api/v1/diplomatic/formulae/").data["results"][0]["occurrences"][0]

        assert occurrence["charter"] == _charter_of(text)
        assert occurrence["excerpt"] == "anathema sit"

    def test_a_relation_names_its_charter(self, api_client):
        text = _published()
        Relation.objects.create(image_text=text, subject="a", predicate=Relation.Predicate.GRANTED_BY, object="b")

        assert api_client.get("/api/v1/diplomatic/relations/").data["results"][0]["charter"] == _charter_of(text)

    def test_a_charter_without_a_shelfmark_or_a_date_says_so_with_empty_strings(self, api_client):
        text = _published()
        part = text.item_image.item_part
        part.current_item = None
        part.save()
        item = part.historical_item
        item.date = None
        item.save()
        CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.PLACE, name="Edinburgh")

        charter = api_client.get("/api/v1/diplomatic/entities/").data["results"][0]["charter"]

        assert (charter["shelfmark"], charter["repository"], charter["date"]) == ("", "", "")

    @pytest.mark.parametrize("rows", [1, 6])
    def test_naming_the_charters_costs_no_query_per_row(self, api_client, django_assert_max_num_queries, rows):
        formula = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="anathema", exemplar="a")
        for _ in range(rows):
            text = _published()
            CharterEntity.objects.create(image_text=text, role=CharterEntity.Role.WITNESS, name="Walterus")
            Relation.objects.create(image_text=text, subject="a", predicate=Relation.Predicate.GRANTED_BY, object="b")
            FormulaOccurrence.objects.create(formula=formula, image_text=text, excerpt="a")

        # Count, page, and for the formulary its prefetch: the same for one row as for six.
        for url in ("/api/v1/diplomatic/entities/", "/api/v1/diplomatic/relations/"):
            with django_assert_max_num_queries(2):
                api_client.get(url)
        with django_assert_max_num_queries(3):
            api_client.get("/api/v1/diplomatic/formulae/")


@pytest.mark.django_db
class TestFormularySearch:
    def test_search_finds_a_formula_by_its_wording_or_its_published_type(self, api_client):
        text = _published()
        curse = Formula.objects.create(kind=Formula.Kind.SANCTIO, label="Curse", exemplar="anathema sit")
        seal = Formula.objects.create(
            kind=Formula.Kind.CORROBORATIO, label="Sealing", exemplar="sigilli mei", published_type="Corroboratio A"
        )
        for formula in (curse, seal):
            FormulaOccurrence.objects.create(formula=formula, image_text=text, excerpt="x")

        def labels(query):
            return [
                row["label"] for row in api_client.get(f"/api/v1/diplomatic/formulae/?search={query}").data["results"]
            ]

        assert labels("anathema") == ["Curse"]
        assert labels("Corroboratio A") == ["Sealing"]

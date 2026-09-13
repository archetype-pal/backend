"""The runner and the review gate.

The invariant these hold to: running a pipeline creates proposals and nothing
else, and only `accept()` — with a named human on it — creates a record.
"""

from unittest import mock

import pytest

from apps.diplomatic import services
from apps.diplomatic.models import CharterEntity, Formula, FormulaOccurrence, Proposal, Relation
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult
from apps.users.tests.factories import SuperuserFactory, UserFactory


class _Answering:
    """A provider that returns a fixed answer, so the runner can be exercised."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def run(self, request: InferenceRequest) -> InferenceResult:
        self.calls += 1
        return InferenceResult(output={"text": self.text}, model_name="stub", cost_micros=10)


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


def _stub(text: str):
    provider = _Answering(text)
    registration = mock.Mock(name="openrouter", hosted=True, factory=lambda: provider)
    registration.name = "openrouter"
    patch = mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration)
    return provider, patch


@pytest.mark.django_db
class TestRun:
    def test_a_run_creates_proposals_and_no_records(self, enabled):
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        provider, patch = _stub('{"entities": [{"role": "witness", "name": "Walterus"}]}')

        with patch:
            tally = services.run("W2.1")

        assert tally == {"selected": 1, "proposed": 1, "refused": 0, "failed": 0, "unparsable": 0}
        assert Proposal.objects.count() == 1
        # The gate, stated as an assertion: the pipeline ran and the canonical
        # tables are still empty.
        assert CharterEntity.objects.count() == 0

    def test_a_dry_run_calls_no_model(self, enabled):
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        provider, patch = _stub("{}")

        with patch:
            tally = services.run("W2.1", dry_run=True)

        assert provider.calls == 0
        assert tally["selected"] == 1
        assert Proposal.objects.count() == 0
        assert MLJob.objects.count() == 0

    def test_an_unusable_answer_is_counted_not_proposed(self, enabled):
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        provider, patch = _stub("I could not find any entities.")

        with patch:
            tally = services.run("W2.1")

        assert tally["unparsable"] == 1
        assert Proposal.objects.count() == 0
        # The call was still made and billed; losing that would hide real spend.
        assert MLJob.objects.filter(status=MLJob.Status.SUCCEEDED).count() == 1

    def test_the_limit_bounds_the_corpus_pass(self, enabled):
        for _ in range(3):
            ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        provider, patch = _stub('{"entities": []}')

        with patch:
            tally = services.run("W2.1", limit=2)

        assert tally["selected"] == 2
        assert provider.calls == 2

    def test_a_refusal_stops_the_run_rather_than_grinding_through_it(self, enabled, settings):
        settings.ML_INFERENCE_ENABLED = False
        for _ in range(3):
            ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        provider, patch = _stub('{"entities": []}')

        with patch:
            tally = services.run("W2.1")

        assert tally["refused"] == 1
        assert tally["selected"] == 1
        assert provider.calls == 0

    def test_the_hosted_gate_refuses_before_any_call(self, enabled, settings):
        settings.ML_HOSTED_PROVIDERS_ENABLED = False
        ImageTextFactory(type=ImageText.Type.TRANSCRIPTION, content="Sciant presentes")
        provider, patch = _stub('{"entities": []}')

        with patch:
            tally = services.run("W2.1")

        assert tally["refused"] == 1
        assert provider.calls == 0


@pytest.mark.django_db
class TestAccept:
    def _proposal(self, pipeline, payload, source):
        return Proposal.objects.create(pipeline=pipeline, source_type="imagetext", source_id=source.pk, payload=payload)

    def test_accepting_entities_writes_them_against_the_reviewer(self):
        text = ImageTextFactory()
        proposal = self._proposal(
            "W2.1", {"entities": [{"role": "witness", "name": "Walterus", "normalised": "", "note": ""}]}, text
        )
        reviewer = SuperuserFactory()

        created = services.accept(proposal, reviewer=reviewer)

        assert len(created) == 1
        proposal.refresh_from_db()
        assert proposal.status == Proposal.Status.ACCEPTED
        assert proposal.reviewer == reviewer
        assert CharterEntity.objects.get().name == "Walterus"

    def test_an_anonymous_reviewer_cannot_accept(self):
        from django.contrib.auth.models import AnonymousUser

        text = ImageTextFactory()
        proposal = self._proposal("W2.1", {"entities": []}, text)

        with pytest.raises(services.PipelineError, match="authenticated"):
            services.accept(proposal, reviewer=AnonymousUser())

        assert Proposal.objects.get().status == Proposal.Status.PENDING

    def test_a_decided_proposal_cannot_be_accepted_twice(self):
        text = ImageTextFactory()
        proposal = self._proposal("W2.1", {"entities": [{"role": "place", "name": "Perth"}]}, text)
        services.accept(proposal, reviewer=UserFactory())

        with pytest.raises(services.PipelineError, match="already"):
            services.accept(proposal, reviewer=UserFactory())

        assert CharterEntity.objects.count() == 1

    def test_accepting_formulae_clusters_on_kind_and_label(self):
        first, second = ImageTextFactory(), ImageTextFactory()
        payload = {"formulae": [{"kind": "sanctio", "label": "anathema", "excerpt": "a", "published_type": ""}]}
        reviewer = UserFactory()

        services.accept(self._proposal("W2.2", payload, first), reviewer=reviewer)
        payload_two = {"formulae": [{"kind": "sanctio", "label": "anathema", "excerpt": "b", "published_type": ""}]}
        services.accept(self._proposal("W2.2", payload_two, second), reviewer=reviewer)

        # One cluster, two wordings — which is the variation the item measures.
        assert Formula.objects.count() == 1
        assert FormulaOccurrence.objects.count() == 2

    def test_accepting_triples_writes_relations(self):
        text = ImageTextFactory()
        payload = {"triples": [{"subject": "Walterus", "predicate": "witnessed_by", "object": "David"}]}

        services.accept(self._proposal("W3.3", payload, text), reviewer=UserFactory())

        assert Relation.objects.get().predicate == "witnessed_by"

    def test_a_translation_draft_is_created_as_a_draft_and_marked_machine(self):
        source = ImageTextFactory(type=ImageText.Type.TRANSCRIPTION)
        job = MLJob.objects.create(task="W2.4", provider="openrouter", model_name="stub")
        proposal = Proposal.objects.create(
            pipeline="W2.4",
            source_type="imagetext",
            source_id=source.pk,
            payload={"translation": "Know all present", "notes": ""},
            ml_job=job,
        )

        created = services.accept(proposal, reviewer=UserFactory())

        draft = created[0]
        assert draft.status == ImageText.Status.DRAFT
        assert 'resp="#machine-draft"' in draft.content
        assert 'source="stub"' in draft.content

    def test_a_draft_never_overwrites_a_human_translation(self):
        image = ItemImageFactory()
        source = ImageTextFactory(item_image=image, type=ImageText.Type.TRANSCRIPTION)
        ImageTextFactory(item_image=image, type=ImageText.Type.TRANSLATION, content="A scholar's translation")
        proposal = Proposal.objects.create(
            pipeline="W2.4",
            source_type="imagetext",
            source_id=source.pk,
            payload={"translation": "Machine draft", "notes": ""},
        )

        with pytest.raises(services.PipelineError, match="already has a translation"):
            services.accept(proposal, reviewer=UserFactory())

        assert ImageText.objects.filter(type=ImageText.Type.TRANSLATION).count() == 1
        assert Proposal.objects.get().status == Proposal.Status.PENDING

    def test_accepting_a_dating_flag_records_the_judgement_and_changes_no_date(self):
        text = ImageTextFactory()
        original = text.item_image.item_part.historical_item.date.date
        proposal = self._proposal(
            "W3.2", {"verdict": "inconsistent", "evidence": "x", "reasoning": "y", "suggested_range": "1165x1177"}, text
        )

        created = services.accept(proposal, reviewer=UserFactory())

        assert created == []
        text.item_image.item_part.historical_item.refresh_from_db()
        assert text.item_image.item_part.historical_item.date.date == original


@pytest.mark.django_db
class TestReject:
    def test_rejecting_records_the_reason(self):
        text = ImageTextFactory()
        proposal = Proposal.objects.create(
            pipeline="W2.1", source_type="imagetext", source_id=text.pk, payload={"entities": []}
        )

        services.reject(proposal, reviewer=UserFactory(), reason="Witness list misread.")

        proposal.refresh_from_db()
        assert proposal.status == Proposal.Status.REJECTED
        assert proposal.reason == "Witness list misread."

    def test_queue_depth_counts_only_undecided(self):
        text = ImageTextFactory()
        for _ in range(3):
            Proposal.objects.create(
                pipeline="W2.1", source_type="imagetext", source_id=text.pk, payload={"entities": []}
            )
        services.reject(Proposal.objects.first(), reviewer=UserFactory())

        assert services.queue_depth() == 2
        assert services.queue_depth("W2.2") == 0

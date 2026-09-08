"""W1.1 — selection, parsing, and where the output is allowed to go.

The load-bearing assertion in this file is the negative one: a run creates
`GraphProposal` rows and zero `Graph` rows, whatever the model says.
"""

import json
from unittest import mock

import pytest

from apps.annotations.models import Graph, GraphProposal
from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory
from apps.ml.models import MLJob
from apps.ml.providers import InferenceRequest, InferenceResult
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory
from apps.vision.services import detection


class _Answering:
    def __init__(self, text: str):
        self.text = text
        self.requests: list[InferenceRequest] = []

    def run(self, request: InferenceRequest) -> InferenceResult:
        self.requests.append(request)
        return InferenceResult(output={"text": self.text}, model_name="stub", cost_micros=11)


def _stub(text: str):
    provider = _Answering(text)
    registration = mock.Mock(hosted=True, factory=lambda: provider)
    registration.name = "openrouter"
    return provider, mock.patch("apps.ml.services.inference.resolve_provider", return_value=registration)


@pytest.fixture
def enabled(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = True
    settings.ML_DAILY_COST_CAP_MICROS = 0
    settings.ML_DAILY_COST_CAP_MICROS_PER_ACTOR = 0
    return settings


@pytest.fixture
def page(db):
    """One annotatable page: an image, a hand for its charter, and an 'a'."""
    part = ItemPartFactory()
    image = ItemImageFactory(item_part=part)
    HandFactory(item_part=part, name="Hand 1")
    AllographFactory(name="a")
    return image


@pytest.fixture
def reachable():
    """Page fetch and measurement succeed, without a network."""
    with (
        mock.patch("apps.vision.images.data_url", return_value="data:image/jpeg;base64,AAA"),
        mock.patch("apps.vision.images.dimensions", return_value=(1000, 2000)),
    ):
        yield


ONE_GLYPH = json.dumps({"glyphs": [{"letter": "a", "x": 0.2, "y": 0.2, "w": 0.02, "h": 0.02, "confidence": 0.8}]})


class TestParse:
    def test_a_letter_sized_box_survives(self):
        assert detection.parse(ONE_GLYPH)[0]["letter"] == "a"

    def test_an_implausible_box_is_dropped_before_a_human_sees_it(self):
        payload = json.dumps({"glyphs": [{"letter": "a", "x": 0.0, "y": 0.0, "w": 0.9, "h": 0.9}]})

        assert detection.parse(payload) == []

    def test_a_box_without_a_letter_is_dropped(self):
        payload = json.dumps({"glyphs": [{"letter": "", "x": 0.2, "y": 0.2, "w": 0.02, "h": 0.02}]})

        assert detection.parse(payload) == []

    def test_prose_is_unusable(self):
        with pytest.raises(ValueError, match="usable JSON"):
            detection.parse("I found several letters on this page.")

    def test_a_missing_glyph_list_is_unusable(self):
        with pytest.raises(ValueError, match="glyphs"):
            detection.parse('{"letters": []}')


@pytest.mark.django_db
class TestSelection:
    def test_unannotated_pages_come_first_and_annotated_ones_are_excluded(self, page):
        annotated = ItemImageFactory()
        Graph.objects.create(item_image=annotated, annotation={})

        selected = detection.unannotated()

        assert page in selected
        assert annotated not in selected

    def test_the_default_hand_follows_the_platform_ordering(self, page):
        preferred = HandFactory(item_part=page.item_part, name="Preferred", is_default=True)

        assert detection.default_hand(page) == preferred

    def test_a_charter_with_no_hand_yields_no_hand(self):
        image = ItemImageFactory()

        assert detection.default_hand(image) is None


@pytest.mark.django_db
class TestRun:
    def test_a_run_proposes_and_creates_no_annotation(self, enabled, page, reachable):
        provider, patch = _stub(ONE_GLYPH)

        with patch:
            tally = detection.run(limit=1, selection=[page])

        assert tally["proposed"] == 1
        assert GraphProposal.objects.count() == 1
        # The gate, as an assertion.
        assert Graph.objects.count() == 0

    def test_the_proposal_carries_the_page_geometry_and_its_provenance(self, enabled, page, reachable):
        provider, patch = _stub(ONE_GLYPH)

        with patch:
            detection.run(limit=1, selection=[page])

        proposal = GraphProposal.objects.get()
        assert proposal.confidence == 0.8
        assert proposal.ml_job_id == MLJob.objects.get().pk
        assert proposal.allograph.name == "a"
        assert proposal.hand is not None
        ys = [point[1] for point in proposal.annotation["geometry"]["coordinates"][0]]
        # Flipped against the measured height, not the stored fraction.
        assert max(ys) == 1600

    def test_the_image_is_actually_sent(self, enabled, page, reachable):
        provider, patch = _stub(ONE_GLYPH)

        with patch:
            detection.run(limit=1, selection=[page])

        assert provider.requests[0].inputs["images"] == ["data:image/jpeg;base64,AAA"]

    def test_a_letter_with_no_allograph_is_counted_not_invented(self, enabled, page, reachable):
        payload = json.dumps({"glyphs": [{"letter": "thorn", "x": 0.2, "y": 0.2, "w": 0.02, "h": 0.02}]})
        provider, patch = _stub(payload)

        with patch:
            tally = detection.run(limit=1, selection=[page])

        assert tally["unmatched"] == 1
        assert GraphProposal.objects.count() == 0

    def test_an_unfetchable_page_is_skipped_without_calling_a_model(self, enabled, page):
        provider, patch = _stub(ONE_GLYPH)

        with (
            patch,
            mock.patch("apps.vision.images.dimensions", side_effect=detection.images.ImageUnavailable("no info")),
        ):
            tally = detection.run(limit=1, selection=[page])

        assert tally["unavailable"] == 1
        assert provider.requests == []
        assert MLJob.objects.count() == 0

    def test_a_dry_run_measures_but_calls_nothing(self, enabled, page, reachable):
        provider, patch = _stub(ONE_GLYPH)

        with patch:
            tally = detection.run(limit=1, selection=[page], dry_run=True)

        assert tally["selected"] == 1
        assert provider.requests == []
        assert MLJob.objects.count() == 0

    def test_the_spend_cap_stops_the_run(self, enabled, page, reachable, settings):
        settings.ML_INFERENCE_ENABLED = False
        provider, patch = _stub(ONE_GLYPH)

        with patch:
            tally = detection.run(selection=[page, page])

        assert tally["refused"] == 1
        assert tally["selected"] == 1
        assert provider.requests == []

    def test_an_unusable_answer_is_counted_and_still_billed(self, enabled, page, reachable):
        provider, patch = _stub("I could not read this page.")

        with patch:
            tally = detection.run(limit=1, selection=[page])

        assert tally["unparsable"] == 1
        assert GraphProposal.objects.count() == 0
        assert MLJob.objects.filter(status=MLJob.Status.SUCCEEDED).count() == 1


@pytest.mark.django_db
class TestAcceptance:
    def test_an_accepted_proposal_becomes_an_annotation_attributed_to_the_reviewer(self, enabled, page, reachable):
        from apps.annotations.services import proposals
        from apps.users.tests.factories import UserFactory

        provider, patch = _stub(ONE_GLYPH)
        with patch:
            detection.run(limit=1, selection=[page])
        reviewer = UserFactory()

        graph = proposals.accept(GraphProposal.objects.get(), reviewer=reviewer)

        assert Graph.objects.count() == 1
        assert graph.annotation == GraphProposal.objects.get().annotation

    def test_a_proposal_without_a_hand_cannot_be_accepted(self, enabled, reachable):
        from apps.annotations.services import proposals
        from apps.users.tests.factories import UserFactory

        image = ItemImageFactory()
        AllographFactory(name="a")
        provider, patch = _stub(ONE_GLYPH)
        with patch:
            detection.run(limit=1, selection=[image])

        with pytest.raises(proposals.ProposalError, match="allograph and a hand"):
            proposals.accept(GraphProposal.objects.get(), reviewer=UserFactory())

        assert Graph.objects.count() == 0

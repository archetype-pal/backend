"""W3.5 and W3.6: asking a model about one shape, from the viewer."""

from unittest import mock

from django.contrib.auth import get_user_model
import pytest
from rest_framework.test import APIClient

from apps.annotations.models import Graph, GraphProposal
from apps.annotations.tests.factories import GraphFactory
from apps.manuscripts.models import ImageText
from apps.manuscripts.tests.factories import ImageTextFactory, ItemImageFactory
from apps.ml.tests.factories import MLJobFactory
from apps.scribes.tests.factories import HandDescriptionFactory, HandFactory
from apps.symbols_structure.models import AllographComponentFeature
from apps.symbols_structure.tests.factories import (
    AllographComponentFactory,
    AllographFactory,
    ComponentFactory,
    FeatureFactory,
)
from apps.vision import images
from apps.vision.models import GraphExplanation
from apps.vision.services import glyph_assist

pytestmark = pytest.mark.django_db

RING = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[10, 10], [40, 10], [40, 40], [10, 40], [10, 10]]]},
}
WHOLE_PAGE = {
    "type": "Feature",
    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1000, 0], [1000, 1000], [0, 1000], [0, 0]]]},
}


@pytest.fixture
def user():
    return get_user_model().objects.create_user(username="reader", password="x")


@pytest.fixture
def client(user):
    api = APIClient(HTTP_HOST="localhost")
    api.force_authenticate(user)
    return api


@pytest.fixture
def form():
    allograph = AllographFactory()
    row = AllographComponentFactory(allograph=allograph, component=ComponentFactory())
    feature = FeatureFactory()
    AllographComponentFeature.objects.create(allograph_component=row, feature=feature)
    allograph.test_component, allograph.test_feature = row.component_id, feature.pk
    return allograph


@pytest.fixture
def page():
    return ItemImageFactory()


@pytest.fixture
def switched_on(settings):
    settings.ML_INFERENCE_ENABLED = True
    settings.ML_HOSTED_PROVIDERS_ENABLED = True
    with (
        mock.patch.object(images, "dimensions", return_value=(1000, 1000)),
        mock.patch.object(glyph_assist, "pictures_of", return_value=["data:image/jpeg;base64,AA=="]),
        mock.patch.object(glyph_assist, "_example_pictures", return_value=[]),
    ):
        yield


def _answered(answer):
    return mock.patch.object(glyph_assist, "_ask", return_value=(MLJobFactory(model_name="claude-opus-5-5"), answer))


class TestTheAnswerIsKeptToTheTaxonomy:
    def test_invented_ids_are_dropped(self, form, page):
        hand = HandFactory(item_part=page.item_part)
        forms = glyph_assist._forms()

        settled = glyph_assist.settle_suggestion(
            {
                "allograph": form.pk,
                "hand": 999999,
                "components": [
                    {"component": form.test_component, "features": [form.test_feature, 999999]},
                    {"component": 999999, "features": []},
                ],
                "positions": [999999],
                "alternatives": [{"allograph": 999999, "why": "made up"}],
                "confidence": 7,
            },
            forms,
            [hand],
        )

        assert settled["allograph"] == form.pk
        assert settled["confidence"] == 1.0
        # One hand on the page: there is nothing to choose.
        assert settled["hand"] == hand.pk
        assert [row["component"] for row in settled["description"]["components"]] == [form.test_component]
        assert settled["description"]["components"][0]["features"] == [form.test_feature]
        assert settled["description"]["positions"] == []
        assert settled["description"]["alternatives"] == []

    def test_an_unknown_allograph_carries_nothing_with_it(self, form):
        settled = glyph_assist.settle_suggestion(
            {"allograph": 999999, "components": [{"component": form.test_component}], "problem": "Two letters."},
            glyph_assist._forms(),
            [],
        )

        assert settled["allograph"] is None
        assert settled["description"]["components"] == []
        assert settled["description"]["problem"] == "Two letters."

    def test_a_disagreement_must_name_an_allograph_there_is(self, form):
        forms = glyph_assist._forms()

        vague = glyph_assist.settle_explanation({"verdict": "disagree", "alternative": 999999}, forms, current=form.pk)
        assert vague["verdict"] == "doubtful"

        other = AllographFactory()
        clear = glyph_assist.settle_explanation(
            {"verdict": "disagree", "alternative": other.pk, "reasons": [{"basis": "invented", "text": "x"}]},
            glyph_assist._forms(),
            current=form.pk,
        )
        assert clear["alternative"]["allograph"] == other.pk
        assert clear["reasons"] == []


class TestTheRecord:
    def test_it_holds_the_catalogue_the_hands_and_the_texts(self, page, user):
        hand = HandFactory(item_part=page.item_part)
        hand.item_part_images.add(page)
        HandDescriptionFactory(hand=hand, content="<p>Upright, with a broad pen.</p>")
        ImageTextFactory(item_image=page, status=ImageText.Status.LIVE, content="<p>Sciant presentes</p>")

        record = glyph_assist.image_record(page, user)

        assert page.item_part.current_item.shelfmark in record
        assert "Upright, with a broad pen." in record
        assert "Sciant presentes" in record

    def test_a_draft_only_reaches_the_model_for_someone_who_may_read_it(self, page, user):
        ImageTextFactory(item_image=page, status=ImageText.Status.DRAFT, content="<p>Unpublished words</p>")

        assert "Unpublished words" not in glyph_assist.image_record(page, user)

        staff = get_user_model().objects.create_user(username="staff", password="x", is_staff=True)
        assert "Unpublished words" in glyph_assist.image_record(page, staff)

    def test_the_surroundings_name_the_letters_nearest_first(self, page, form):
        near = GraphFactory(item_image=page, allograph=form, annotation=RING)
        far_ring = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[800, 800], [820, 800], [820, 820], [800, 820], [800, 800]]],
            },
        }
        GraphFactory(item_image=page, allograph=AllographFactory(), annotation=far_ring)

        lines = glyph_assist.surroundings(page, glyph_assist.Box(50, 960, 20, 20), 1000)

        assert lines[0].startswith(glyph_assist._form_label(near.allograph))


class TestReadingTheAnswer:
    def test_prose_around_the_object_is_tolerated(self):
        assert glyph_assist._json_part('The box sits in "hoc". {"allograph": 1}') == '{"allograph": 1}'

    def test_a_loose_box_is_named_not_refused(self):
        assert "centred on" in glyph_assist.SUGGEST_SYSTEM


class TestDirections:
    def test_a_letter_over_the_place_is_said_to_overlap_it(self):
        box = glyph_assist.Box(10, 10, 20, 20)

        assert glyph_assist._direction(box, glyph_assist.Box(15, 15, 20, 20)) == "overlapping this place"
        assert "to the right" in glyph_assist._direction(box, glyph_assist.Box(100, 12, 20, 20))


class TestSuggest:
    URL = "/api/v1/vision/pages/{}/suggest/"

    def test_it_files_a_proposal_only_the_asker_settles(self, client, user, page, form, switched_on):
        answer = {"allograph": form.pk, "confidence": 0.8, "reasoning": "A round bowl."}

        with _answered(answer):
            reply = client.post(self.URL.format(page.pk), {"annotation": RING}, format="json")

        assert reply.status_code == 201, reply.data
        assert reply.data["allograph"] == form.pk
        assert reply.data["reasoning"] == "A round bowl."
        proposal = GraphProposal.objects.get(pk=reply.data["id"])
        assert proposal.requested_by == user
        assert proposal.status == GraphProposal.Status.PENDING
        assert not Graph.objects.filter(item_image=page).exists()

    def test_the_allograph_a_researcher_chose_stands(self, client, page, form, switched_on):
        chosen = AllographFactory()

        with _answered({"allograph": form.pk}):
            reply = client.post(self.URL.format(page.pk), {"annotation": RING, "allograph": chosen.pk}, format="json")

        assert reply.data["allograph"] == chosen.pk

    def test_a_box_over_most_of_the_page_is_refused_before_it_costs_anything(self, client, page, switched_on):
        with mock.patch.object(glyph_assist, "_ask") as ask:
            reply = client.post(self.URL.format(page.pk), {"annotation": WHOLE_PAGE}, format="json")

        assert reply.status_code == 400
        ask.assert_not_called()

    def test_anyone_signed_out_is_refused(self, page):
        reply = APIClient(HTTP_HOST="localhost").post(self.URL.format(page.pk), {"annotation": RING}, format="json")

        assert reply.status_code in (401, 403)

    def test_switched_off_it_says_so_in_words(self, client, page, switched_on, settings):
        settings.ML_HOSTED_PROVIDERS_ENABLED = False

        reply = client.post(self.URL.format(page.pk), {"annotation": RING}, format="json")

        assert reply.status_code == 503
        assert "ML_" not in reply.data["detail"]
        assert client.get("/api/v1/vision/assist/").data == {"enabled": False}

    def test_at_the_cap_it_says_so_in_words(self, client, page, switched_on):
        with mock.patch.object(glyph_assist.budget, "check", side_effect=glyph_assist.BudgetExceeded("1 micros")):
            reply = client.post(self.URL.format(page.pk), {"annotation": RING}, format="json")

        assert reply.status_code == 429
        assert "micros" not in reply.data["detail"]


class TestReject:
    URL = "/api/v1/vision/suggestions/{}/reject/"

    def _suggestion(self, page, asker):
        return GraphProposal.objects.create(item_image=page, annotation=RING, requested_by=asker)

    def test_the_asker_can_turn_it_down_once(self, client, user, page):
        proposal = self._suggestion(page, user)

        assert client.post(self.URL.format(proposal.pk), {"reason": "two letters"}, format="json").status_code == 200
        proposal.refresh_from_db()
        assert proposal.status == GraphProposal.Status.REJECTED
        assert proposal.reason == "two letters"
        assert client.post(self.URL.format(proposal.pk), {}, format="json").status_code == 409

    def test_nobody_else_can(self, client, page):
        other = get_user_model().objects.create_user(username="other", password="x")

        assert client.post(self.URL.format(self._suggestion(page, other).pk), {}, format="json").status_code == 404

    def test_a_bulk_proposal_is_not_theirs_to_decide(self, client, page):
        proposal = GraphProposal.objects.create(item_image=page, annotation=RING)

        assert client.post(self.URL.format(proposal.pk), {}, format="json").status_code == 404


class TestExplain:
    URL = "/api/v1/vision/graphs/{}/explain/"
    ANSWER = {"verdict": "obvious", "summary": "A plain g.", "reasons": [{"basis": "form", "text": "A lower bow."}]}

    def _graph(self, form, page):
        return GraphFactory(
            item_image=page, allograph=form, annotation=RING, annotation_type=Graph.AnnotationType.IMAGE
        )

    def test_it_answers_and_keeps_the_answer(self, client, form, page, switched_on):
        graph = self._graph(form, page)

        with _answered(self.ANSWER) as ask:
            first = client.post(self.URL.format(graph.pk), {}, format="json")
            again = client.post(self.URL.format(graph.pk), {}, format="json")

        assert first.status_code == 200, first.data
        assert first.data["verdict"] == "obvious"
        assert first.data["reasons"] == self.ANSWER["reasons"]
        assert again.data["id"] == first.data["id"]
        assert ask.call_count == 1

    def test_a_changed_annotation_is_asked_about_afresh(self, client, form, page, switched_on):
        graph = self._graph(form, page)

        with _answered(self.ANSWER) as ask:
            client.post(self.URL.format(graph.pk), {}, format="json")
            Graph.objects.filter(pk=graph.pk).update(note="Doubtful: could be q.")
            client.post(self.URL.format(graph.pk), {}, format="json")

        assert ask.call_count == 2
        assert GraphExplanation.objects.filter(graph=graph).count() == 2

    def test_another_language_is_another_answer(self, client, form, page, switched_on):
        graph = self._graph(form, page)

        with _answered(self.ANSWER) as ask:
            client.post(self.URL.format(graph.pk), {}, format="json")
            french = client.post(self.URL.format(graph.pk), {"language": "fr"}, format="json")

        assert ask.call_count == 2
        assert french.data["language"] == "fr"

    def test_a_bare_text_region_cannot_be_explained(self, client, page, switched_on):
        region = GraphFactory(
            item_image=page, allograph=None, hand=None, annotation=RING, annotation_type=Graph.AnnotationType.TEXT
        )

        assert client.post(self.URL.format(region.pk), {}, format="json").status_code == 400

    def test_anyone_signed_out_is_refused(self, form, page):
        graph = self._graph(form, page)

        assert APIClient(HTTP_HOST="localhost").post(self.URL.format(graph.pk), {}, format="json").status_code in (
            401,
            403,
        )

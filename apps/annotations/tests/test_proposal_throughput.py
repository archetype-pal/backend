"""What the review queue gets through, model by model (W1.1's throughput claim).

The numbers have to be honest in the directions they could flatter a model: a
corrected proposal is not a model's success, a break is not time spent, and a
graph an accept created is not an annotation drawn by hand.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone
import pytest

from apps.annotations.models import GraphProposal
from apps.annotations.services import proposals, throughput
from apps.common.models import EditEvent
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.tests.factories import MLJobFactory
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory

BOX = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [9, 0], [9, 9], [0, 9], [0, 0]]]}}
NOW = timezone.now().replace(microsecond=0)
WINDOW = {"since": NOW - timedelta(days=7), "until": NOW + timedelta(days=1)}


@pytest.fixture
def reviewer(django_user_model):
    return django_user_model.objects.create_user(username="reviewer", password="x")


def _job(version="r1"):
    return MLJobFactory(task="W1.1", provider="letters", model_name="letters on catmus", model_version=version)


def _filed(job, *, created=None):
    proposal = proposals.propose(
        item_image_id=ItemImageFactory().pk,
        annotation=BOX,
        allograph_id=AllographFactory().pk,
        hand_id=HandFactory().pk,
        ml_job_id=job.pk,
    )
    if created is not None:
        GraphProposal.objects.filter(pk=proposal.pk).update(created=created)
    return proposal


def _decided(proposal, reviewer, *, at, accept=True):
    if accept:
        proposals.accept(proposal, reviewer=reviewer)
    else:
        proposals.reject(proposal, reviewer=reviewer)
    # `reviewed` is stamped with the real clock; the timeline is staged after.
    GraphProposal.objects.filter(pk=proposal.pk).update(reviewed=at)


def _by_hand(actor, *, at, target_id=10_000):
    event = EditEvent.objects.create(
        actor=actor, action=EditEvent.Action.CREATED, target_type="graph", target_id=target_id
    )
    EditEvent.objects.filter(pk=event.pk).update(created=at)


def _model(report, version="r1"):
    (row,) = [row for row in report["models"] if row["model_version"] == version]
    return row


@pytest.mark.django_db
class TestHowOftenAModelIsRight:
    def test_counts_each_outcome_and_a_correction_against_the_model(self, reviewer):
        job = _job()
        right, corrected, wrong, _ = (_filed(job) for _ in range(4))
        proposals.correct(corrected, reviewer=reviewer, allograph_id=AllographFactory().pk)
        _decided(right, reviewer, at=NOW)
        _decided(corrected, reviewer, at=NOW)
        _decided(wrong, reviewer, at=NOW, accept=False)

        row = _model(throughput.report(**WINDOW))

        assert {k: row[k] for k in ("filed", "pending", "accepted_as_filed", "accepted_corrected", "rejected")} == {
            "filed": 4,
            "pending": 1,
            "accepted_as_filed": 1,
            "accepted_corrected": 1,
            "rejected": 1,
        }
        assert (row["corrected_letter"], row["corrected_box"], row["corrected_hand"]) == (1, 0, 0)
        assert row["acceptance_rate"] == pytest.approx(1 / 3, abs=1e-3)
        assert row["accepted_rate"] == pytest.approx(2 / 3, abs=1e-3)

    def test_each_model_version_is_reported_apart(self, reviewer):
        _filed(_job("r1"))
        _filed(_job("r2"))

        report = throughput.report(**WINDOW)

        assert [row["model_version"] for row in report["models"]] == ["r1", "r2"]

    def test_counts_only_the_proposals_filed_in_the_window(self):
        _filed(_job(), created=NOW - timedelta(days=30))

        assert throughput.report(**WINDOW)["models"] == []


@pytest.mark.django_db
class TestTimePerDecision:
    def test_a_decision_costs_the_gap_since_the_reviewer_s_last_action(self, reviewer):
        job = _job()
        first, second, third, after_a_break = (_filed(job) for _ in range(4))
        _decided(first, reviewer, at=NOW)
        _decided(second, reviewer, at=NOW + timedelta(seconds=20))
        _decided(third, reviewer, at=NOW + timedelta(seconds=50), accept=False)
        _decided(after_a_break, reviewer, at=NOW + timedelta(minutes=30))

        timing = _model(throughput.report(**WINDOW))["decision_time"]

        assert (timing["actions"], timing["timed"], timing["accepted"]) == (4, 2, 3)
        assert (timing["seconds"], timing["mean_seconds"], timing["median_seconds"]) == (50, 25, 25)

    def test_the_time_per_annotation_made_includes_the_rejections(self, reviewer):
        job = _job()
        kept, dropped = _filed(job), _filed(job)
        _by_hand(reviewer, at=NOW)
        _decided(dropped, reviewer, at=NOW + timedelta(seconds=10), accept=False)
        _decided(kept, reviewer, at=NOW + timedelta(seconds=30))

        row = _model(throughput.report(**WINDOW))

        # 30 s over two decisions, one of which made an annotation.
        assert row["seconds_per_accepted"] == 30

    def test_a_proposal_filed_earlier_but_decided_in_the_window_is_timed(self, reviewer):
        job = _job()
        old, new = _filed(job, created=NOW - timedelta(days=30)), _filed(job)
        _decided(old, reviewer, at=NOW)
        _decided(new, reviewer, at=NOW + timedelta(seconds=40))

        row = _model(throughput.report(**WINDOW))

        assert row["filed"] == 1
        assert row["decision_time"]["timed"] == 1
        assert row["decision_time"]["seconds"] == 40


@pytest.mark.django_db
class TestAgainstAnnotatingByHand:
    def test_hand_annotations_and_decisions_share_one_timeline(self, reviewer):
        job = _job()
        proposal = _filed(job)
        _by_hand(reviewer, at=NOW)
        _decided(proposal, reviewer, at=NOW + timedelta(seconds=15))
        _by_hand(reviewer, at=NOW + timedelta(seconds=75))

        report = throughput.report(**WINDOW)

        # Each gap is counted once, against the action that ended it.
        assert report["by_hand"]["seconds"] == 60
        assert _model(report)["decision_time"]["seconds"] == 15

    def test_a_graph_an_accept_created_is_not_counted_as_drawn_by_hand(self, reviewer):
        _decided(_filed(_job()), reviewer, at=NOW)

        assert throughput.report(**WINDOW)["by_hand"]["actions"] == 0

    def test_the_speedup_is_the_ratio_of_the_two_times(self, reviewer, django_user_model):
        annotator = django_user_model.objects.create_user(username="annotator", password="x")
        for second in (0, 60, 120):
            _by_hand(annotator, at=NOW + timedelta(seconds=second))
        job = _job()
        for second in (0, 20, 40):
            _decided(_filed(job), reviewer, at=NOW + timedelta(seconds=second))

        row = _model(throughput.report(**WINDOW))

        assert row["seconds_per_accepted"] == 20
        assert row["speedup"] == 3


@pytest.mark.django_db
class TestReport:
    URL = "/api/v1/management/annotations/proposals/throughput/"

    def test_the_endpoint_reports_the_window_asked_for(self, management_client, reviewer):
        _decided(_filed(_job()), reviewer, at=NOW)

        response = management_client.get(self.URL, {"since": (NOW - timedelta(days=1)).date().isoformat()})

        assert response.status_code == 200, response.json()
        assert [row["model_version"] for row in response.json()["models"]] == ["r1"]

    @pytest.mark.parametrize(
        "params",
        [
            pytest.param({}, id="no start"),
            pytest.param({"since": "yesterday"}, id="not a date"),
            pytest.param({"since": "2026-11-05", "until": "2026-11-01"}, id="ends before it starts"),
        ],
    )
    def test_a_window_that_cannot_be_read_is_refused(self, management_client, params):
        assert management_client.get(self.URL, params).status_code == 400

    def test_the_command_prints_each_model_and_the_hand_baseline(self, reviewer):
        job = _job()
        right, wrong = _filed(job), _filed(job)
        _decided(right, reviewer, at=NOW)
        _decided(wrong, reviewer, at=NOW + timedelta(seconds=30), accept=False)
        out = StringIO()

        call_command("proposal_throughput", since=(NOW - timedelta(days=1)).strftime("%Y-%m-%d"), stdout=out)

        output = out.getvalue()
        assert "W1.1 letters on catmus @ r1" in output
        assert "right as filed: 50% of 2 decided" in output
        assert "by hand: 0 annotations" in output

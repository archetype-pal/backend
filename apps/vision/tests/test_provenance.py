"""What a model's accepted output became, in the ledger."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone
import pytest

from apps.annotations.services import proposals
from apps.manuscripts.tests.factories import ItemImageFactory
from apps.ml.models import MLJob
from apps.ml.services import ledger
from apps.ml.tests.factories import MLJobFactory
from apps.scribes.tests.factories import HandFactory
from apps.symbols_structure.tests.factories import AllographFactory
from apps.vision.models import LetterRequest, PageDraft

BOX = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 2]]]}}

pytestmark = pytest.mark.django_db


def test_an_accepted_proposal_is_found_from_its_graph(django_user_model):
    job = MLJobFactory()
    proposal = proposals.propose(
        item_image_id=ItemImageFactory().pk,
        annotation=BOX,
        allograph_id=AllographFactory().pk,
        hand_id=HandFactory().pk,
        ml_job_id=job.pk,
    )

    graph = proposals.accept(proposal, reviewer=django_user_model.objects.create_user(username="r", password="x"))

    assert list(ledger.jobs_touching("graph", graph.pk)) == [job]


def test_the_command_closes_stuck_jobs_and_requests():
    job = MLJobFactory(status=MLJob.Status.RUNNING)
    MLJob.objects.filter(pk=job.pk).update(created=timezone.now() - timedelta(hours=3))
    draft = PageDraft.objects.create(item_image=ItemImageFactory(), status=PageDraft.Status.WORKING)
    letters = LetterRequest.objects.create(item_image=ItemImageFactory(), status=LetterRequest.Status.WORKING)
    long_ago = timezone.now() - timedelta(days=1)
    PageDraft.objects.filter(pk=draft.pk).update(updated=long_ago)
    LetterRequest.objects.filter(pk=letters.pk).update(updated=long_ago)
    out = StringIO()

    call_command("close_abandoned_jobs", stdout=out)

    draft.refresh_from_db(), letters.refresh_from_db()
    assert draft.status == PageDraft.Status.FAILED
    assert letters.status == LetterRequest.Status.FAILED
    assert "Closed 1 jobs and 2 page requests." in out.getvalue()

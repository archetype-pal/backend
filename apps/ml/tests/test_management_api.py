"""The ledger's read surface — W0.1.

Superuser-gated and read-only: an HTTP write path into a provenance log would be
a way to forge provenance.
"""

import pytest

from apps.ml.models import MLJob

from .factories import MLJobFactory, MLJobTargetFactory

LIST_URL = "/api/v1/management/ml-jobs/"


def _detail(job: MLJob) -> str:
    return f"{LIST_URL}{job.pk}/"


@pytest.mark.django_db
class TestPermissions:
    def test_anonymous_is_refused(self, api_client):
        assert api_client.get(LIST_URL).status_code in (401, 403)

    def test_a_signed_in_non_superuser_is_refused(self, authenticated_client):
        assert authenticated_client.get(LIST_URL).status_code == 403

    def test_a_superuser_may_read(self, management_client):
        assert management_client.get(LIST_URL).status_code == 200


@pytest.mark.django_db
class TestReadOnly:
    def test_the_ledger_cannot_be_written_over_http(self, management_client):
        response = management_client.post(LIST_URL, {"task": "forged"}, format="json")

        assert response.status_code == 405, response.json()
        assert MLJob.objects.count() == 0

    def test_an_entry_cannot_be_edited(self, management_client):
        job = MLJobFactory()

        response = management_client.patch(_detail(job), {"task": "rewritten"}, format="json")

        assert response.status_code == 405
        job.refresh_from_db()
        assert job.task == "W0.1"

    def test_an_entry_cannot_be_deleted(self, management_client):
        job = MLJobFactory()

        assert management_client.delete(_detail(job)).status_code == 405
        assert MLJob.objects.filter(pk=job.pk).exists()


@pytest.mark.django_db
class TestReads:
    def test_detail_includes_the_records_the_inference_touched(self, management_client):
        job = MLJobFactory(model_name="detector-v1")
        MLJobTargetFactory(job=job, target_type="graph", target_id=42)

        body = management_client.get(_detail(job)).json()

        assert body["model_name"] == "detector-v1"
        assert body["targets"] == [{"target_type": "graph", "target_id": 42}]

    def test_the_prompt_itself_is_never_exposed(self, management_client):
        job = MLJobFactory(prompt_hash="b" * 64)

        body = management_client.get(_detail(job)).json()

        assert body["prompt_hash"] == "b" * 64
        assert "prompt" not in body

    def test_filtering_by_target_answers_which_model_produced_this_record(self, management_client):
        wanted = MLJobFactory(model_name="detector-v1")
        MLJobTargetFactory(job=wanted, target_type="graph", target_id=7)
        MLJobTargetFactory(job=MLJobFactory(model_name="other"), target_type="graph", target_id=8)

        body = management_client.get(LIST_URL, {"target_type": "graph", "target_id": 7}).json()
        results = body["results"] if isinstance(body, dict) else body

        assert [row["model_name"] for row in results] == ["detector-v1"]

    def test_filtering_by_status_surfaces_refusals(self, management_client):
        MLJobFactory(status=MLJob.Status.REFUSED, task="W1.1")
        MLJobFactory(status=MLJob.Status.SUCCEEDED, task="W1.2")

        body = management_client.get(LIST_URL, {"status": "refused"}).json()
        results = body["results"] if isinstance(body, dict) else body

        assert [row["task"] for row in results] == ["W1.1"]

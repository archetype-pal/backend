import hashlib
from unittest.mock import MagicMock

import pytest

from apps.manuscripts.tests.factories import ItemImageFactory, ItemPartFactory
from apps.uploads import services
from apps.uploads.models import UploadSession
from apps.uploads.tests.factories import UploadSessionFactory

pytestmark = pytest.mark.django_db

SESSIONS_URL = "/api/v1/uploads/sessions/"


def _create_payload(**overrides):
    payload = {"item_part": ItemPartFactory().pk, "filename": "f12r.tif", "size": 12}
    payload.update(overrides)
    return payload


def test_anonymous_gets_401(api_client):
    assert api_client.post(SESSIONS_URL, _create_payload(), format="json").status_code == 401


def test_non_superuser_gets_403(authenticated_client):
    assert authenticated_client.post(SESSIONS_URL, _create_payload(), format="json").status_code == 403


def test_create_session_returns_contract_fields(management_client, small_chunks):
    response = management_client.post(SESSIONS_URL, _create_payload(locus="f.12r"), format="json")

    assert response.status_code == 201, response.data
    data = response.data
    assert data["status"] == "pending"
    assert data["chunk_size"] == small_chunks
    assert data["total_chunks"] == 3
    assert data["missing_chunks"] == [0, 1, 2]
    assert data["destination_path"].endswith("/f12r.jp2")
    assert data["task"] is None


def test_create_session_conflict_maps_to_409(management_client):
    part = ItemPartFactory()
    ItemImageFactory(item_part=part, image=f"uploads/item-part-{part.pk}/f12r.jp2")
    response = management_client.post(SESSIONS_URL, _create_payload(item_part=part.pk), format="json")
    assert response.status_code == 409


def test_full_chunk_flow_and_finalize(management_client, small_chunks, monkeypatch):
    payload = b"abcdefgh1234"
    create = management_client.post(
        SESSIONS_URL,
        _create_payload(size=len(payload), sha256=hashlib.sha256(payload).hexdigest()),
        format="json",
    )
    session_id = create.data["id"]
    delay = MagicMock(return_value=MagicMock(id="task-9"))
    monkeypatch.setattr("apps.uploads.tasks.ingest_upload.delay", delay)

    for index in range(3):
        chunk = payload[index * 4 : index * 4 + 4]
        response = management_client.put(
            f"{SESSIONS_URL}{session_id}/chunks/{index}/",
            data=chunk,
            content_type="application/octet-stream",
        )
        assert response.status_code == 200, response.data

    response = management_client.post(f"{SESSIONS_URL}{session_id}/finalize/")
    assert response.status_code == 202, response.data
    assert response.data["status"] == "assembled"
    assert response.data["task_id"] == "task-9"
    delay.assert_called_once_with(session_id)

    detail = management_client.get(f"{SESSIONS_URL}{session_id}/")
    assert detail.status_code == 200
    assert detail.data["missing_chunks"] == []


def test_wrong_size_chunk_400s(management_client, small_chunks):
    session_id = management_client.post(SESSIONS_URL, _create_payload(), format="json").data["id"]
    response = management_client.put(
        f"{SESSIONS_URL}{session_id}/chunks/0/", data=b"toolong", content_type="application/octet-stream"
    )
    assert response.status_code == 400


def test_only_owner_may_send_chunks(management_client, small_chunks):
    from rest_framework.test import APIClient

    from apps.users.tests.factories import SuperuserFactory

    session_id = management_client.post(SESSIONS_URL, _create_payload(), format="json").data["id"]
    other = APIClient()
    other.force_authenticate(user=SuperuserFactory())
    response = other.put(f"{SESSIONS_URL}{session_id}/chunks/0/", data=b"abcd", content_type="application/octet-stream")
    assert response.status_code == 409


def test_abort_deletes_session_and_files(management_client, small_chunks):
    session_id = management_client.post(SESSIONS_URL, _create_payload(), format="json").data["id"]
    session = UploadSession.objects.get(pk=session_id)
    assert services.session_tmp_dir(session).exists()

    response = management_client.delete(f"{SESSIONS_URL}{session_id}/")

    assert response.status_code == 204
    assert not UploadSession.objects.filter(pk=session_id).exists()
    assert not services.session_tmp_dir(session).exists()


def test_abort_refused_while_processing():
    from rest_framework.test import APIClient

    session = UploadSessionFactory(status=UploadSession.Status.PROCESSING)
    client = APIClient()
    client.force_authenticate(user=session.owner)
    response = client.delete(f"{SESSIONS_URL}{session.pk}/")
    assert response.status_code == 409


def test_download_original(management_client, tmp_path, settings):
    settings.UPLOADS_ORIGINALS_DIR = str(tmp_path / "originals")
    image = ItemImageFactory(image="uploads/test/x.jp2", original_path="uploads/test/x.tif")
    target = services.originals_root() / "uploads/test/x.tif"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"original-bytes")

    response = management_client.get(f"/api/v1/uploads/item-images/{image.pk}/original/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"original-bytes"

    bare = ItemImageFactory(image="uploads/test/y.jp2")
    assert management_client.get(f"/api/v1/uploads/item-images/{bare.pk}/original/").status_code == 404
    assert management_client.get("/api/v1/uploads/item-images/999999/original/").status_code == 404

import hashlib
from unittest.mock import MagicMock

from PIL import Image
import pytest

from apps.common.models import EditEvent
from apps.manuscripts.models import ItemImage
from apps.uploads import ingest, services
from apps.uploads.models import UploadSession
from apps.uploads.tests.factories import UploadSessionFactory

pytestmark = pytest.mark.django_db


def _assembled_session(tmp_image_format: str = "TIFF", filename: str = "f12r.tif") -> UploadSession:
    """A session in `assembled` state with a real tiny image on disk."""
    session = UploadSessionFactory(
        original_filename=filename,
        destination_path=f"uploads/test/{filename.rsplit('.', 1)[0]}.jp2",
    )
    source = services.assembled_path(session)
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), color="red").save(source, format=tmp_image_format)
    payload = source.read_bytes()
    session.declared_size = len(payload)
    session.computed_sha256 = hashlib.sha256(payload).hexdigest()
    session.status = UploadSession.Status.ASSEMBLED
    session.save()
    return session


@pytest.fixture
def quiet_pipeline(monkeypatch):
    """Stub the two externals the ingest pipeline shells out to: the vips JP2
    conversion and the SIPI tile check."""

    def fake_convert(source, destination):
        destination.write_bytes(b"jp2-bytes")

    monkeypatch.setattr(ingest, "convert_to_jp2", fake_convert)
    monkeypatch.setattr(ingest, "smoke_test_tile", MagicMock())


def test_happy_path_creates_item_image_with_metadata(quiet_pipeline):
    session = _assembled_session()

    payload = ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    image = ItemImage.objects.get(pk=payload["item_image_id"])
    assert session.status == UploadSession.Status.COMPLETE
    assert session.item_image_id == image.pk
    assert image.image.name == session.destination_path
    assert (image.width, image.height) == (20, 10)
    assert image.source_format == "tiff"
    assert image.size_bytes == session.declared_size
    assert image.checksum_sha256 == session.computed_sha256
    assert image.uploaded_by == session.owner
    # Served file present and original archived byte-identically.
    assert (services.media_root() / session.destination_path).read_bytes() == b"jp2-bytes"
    original = services.originals_root() / image.original_path
    assert hashlib.sha256(original.read_bytes()).hexdigest() == session.computed_sha256
    # Temp dir gone, audit row attributed. (Search reindex is manual — the
    # ingest pipeline no longer dispatches it; see the search-engine page.)
    assert not services.session_tmp_dir(session).exists()
    event = EditEvent.objects.filter(target_type="itemimage", target_id=image.pk).latest("id")
    assert event.actor == session.owner


def test_jp2_source_is_placed_without_separate_original(quiet_pipeline):
    session = _assembled_session(tmp_image_format="JPEG2000", filename="direct.jp2")

    payload = ingest.ingest_session(str(session.pk))

    image = ItemImage.objects.get(pk=payload["item_image_id"])
    assert image.original_path == ""
    # Passthrough: served bytes are the upload itself, not a conversion.
    served = (services.media_root() / session.destination_path).read_bytes()
    assert hashlib.sha256(served).hexdigest() == session.computed_sha256


def test_failed_tile_check_cleans_up_and_records_error(quiet_pipeline, monkeypatch):
    monkeypatch.setattr(ingest, "smoke_test_tile", MagicMock(side_effect=ingest.IngestError("tile 500")))
    session = _assembled_session()

    with pytest.raises(ingest.IngestError, match="tile 500"):
        ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == UploadSession.Status.FAILED
    assert "tile 500" in session.error
    assert not (services.media_root() / session.destination_path).exists()
    assert not ItemImage.objects.filter(image=session.destination_path).exists()
    # The assembled source survives for a retry / postmortem until cleanup.
    assert services.assembled_path(session).exists()


def test_duplicate_destination_row_guard(quiet_pipeline):
    from apps.manuscripts.tests.factories import ItemImageFactory

    session = _assembled_session()
    ItemImageFactory(image=session.destination_path)

    with pytest.raises(ingest.IngestError, match="already references"):
        ingest.ingest_session(str(session.pk))
    session.refresh_from_db()
    assert session.status == UploadSession.Status.FAILED


def test_undecodable_file_fails_at_inspection(quiet_pipeline):
    session = UploadSessionFactory(original_filename="fake.tif", destination_path="uploads/test/fake.jp2")
    source = services.assembled_path(session)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"this is not an image")
    session.status = UploadSession.Status.ASSEMBLED
    session.save()

    with pytest.raises(ingest.IngestError, match="not a decodable image"):
        ingest.ingest_session(str(session.pk))


def test_requires_assembled_state():
    session = UploadSessionFactory()
    with pytest.raises(ingest.IngestError, match="expected 'assembled'"):
        ingest.ingest_session(str(session.pk))


def test_task_reports_progress_and_returns_payload(quiet_pipeline, monkeypatch):
    from apps.uploads.tasks import ingest_upload

    session = _assembled_session()
    states = []
    monkeypatch.setattr(ingest_upload, "update_state", lambda **kw: states.append(kw["meta"]["message"]))

    payload = ingest_upload.run(str(session.pk))

    assert payload["destination"] == session.destination_path
    assert any("Converting" in message for message in states)

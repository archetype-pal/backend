import hashlib
from typing import cast
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
    session = cast(
        UploadSession,
        UploadSessionFactory(
            original_filename=filename,
            destination_path=f"uploads/test/{filename.rsplit('.', 1)[0]}.jp2",
        ),
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


def test_happy_path_creates_item_image(quiet_pipeline):
    session = _assembled_session()

    payload = ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    image = ItemImage.objects.get(pk=payload["item_image_id"])
    assert session.status == UploadSession.Status.COMPLETE
    assert session.item_image_id == image.pk
    assert image.image.name == session.destination_path
    assert (services.media_root() / session.destination_path).read_bytes() == b"jp2-bytes"
    # Temp dir gone (the upload original is not kept), audit row attributed. (Search reindex is manual — the
    # ingest pipeline no longer dispatches it; see the search-engine page.)
    assert not services.session_tmp_dir(session).exists()
    event = EditEvent.objects.filter(target_type="itemimage", target_id=image.pk).latest("id")
    assert event.actor == session.owner


def test_jp2_source_is_placed_without_conversion(quiet_pipeline):
    session = _assembled_session(tmp_image_format="JPEG2000", filename="direct.jp2")

    ingest.ingest_session(str(session.pk))

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


def test_unexpected_failure_does_not_leak_its_text_to_the_client(quiet_pipeline, monkeypatch):
    """`session.error` is serialized to the client. A curated IngestError is
    safe to show; anything else can carry internal paths or a traceback."""
    secret = "/app/storage/uploads_tmp/deadbeef/assembled.tif"
    monkeypatch.setattr(ingest, "smoke_test_tile", MagicMock(side_effect=OSError(secret)))
    session = _assembled_session()

    with pytest.raises(OSError):
        ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == UploadSession.Status.FAILED
    assert secret not in session.error
    assert "operator" in session.error


def test_duplicate_destination_row_guard(quiet_pipeline):
    from apps.manuscripts.tests.factories import ItemImageFactory

    session = _assembled_session()
    ItemImageFactory(image=session.destination_path)

    with pytest.raises(ingest.IngestError, match="already references"):
        ingest.ingest_session(str(session.pk))
    session.refresh_from_db()
    assert session.status == UploadSession.Status.FAILED


def test_undecodable_file_is_rejected_before_conversion(quiet_pipeline):
    session = UploadSessionFactory(original_filename="fake.tif", destination_path="uploads/test/fake.jp2")
    source = services.assembled_path(session)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"this is not an image")
    session.status = UploadSession.Status.ASSEMBLED
    session.save()

    with pytest.raises(ingest.IngestError, match="not a decodable image"):
        ingest.ingest_session(str(session.pk))


def test_oversized_master_is_not_mistaken_for_a_bad_file(quiet_pipeline, monkeypatch):
    """Pillow raises DecompressionBombError past 2x MAX_IMAGE_PIXELS (~13400
    square) — reachable for a real manuscript master under the 6 GiB cap. It is
    not an UnidentifiedImageError, so it used to escape verify_decodable and
    fail the session after the whole upload had transferred, even though vips
    converts such a file fine."""
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)  # any real image now trips the guard
    session = _assembled_session()

    payload = ingest.ingest_session(str(session.pk))

    assert ItemImage.objects.filter(pk=payload["item_image_id"]).exists()


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

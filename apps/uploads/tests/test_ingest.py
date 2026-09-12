from typing import cast
from unittest.mock import MagicMock

from PIL import Image
import pytest

from apps.common.models import EditEvent
from apps.manuscripts.models import ItemImage
from apps.uploads import ingest, services
from apps.uploads.models import ImageUploadSession
from apps.uploads.tests.factories import ImageUploadSessionFactory

pytestmark = pytest.mark.django_db


def _assembled_session(tmp_image_format: str = "TIFF", filename: str = "f12r.tif") -> ImageUploadSession:
    """A session in `assembled` state with a real tiny image on disk."""
    session = cast(
        ImageUploadSession,
        ImageUploadSessionFactory(
            original_filename=filename,
            destination_path=f"uploads/test/{filename.rsplit('.', 1)[0]}.jp2",
        ),
    )
    source = services.assembled_path(session)
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 10), color="red").save(source, format=tmp_image_format)
    payload = source.read_bytes()
    session.declared_size = len(payload)
    session.status = ImageUploadSession.Status.ASSEMBLED
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
    assert session.status == ImageUploadSession.Status.COMPLETE
    assert session.item_image_id == image.pk
    assert image.image.name == session.destination_path
    assert (services.media_root() / session.destination_path).read_bytes() == b"jp2-bytes"
    # Temp dir gone (the upload original is not kept), audit row attributed. (Search reindex is manual — the
    # ingest pipeline no longer dispatches it; see the search-engine page.)
    assert not services.session_tmp_dir(session).exists()
    event = EditEvent.objects.filter(target_type="itemimage", target_id=image.pk).latest("id")
    assert event.actor == session.owner


def test_assembles_the_chunks_finalize_left_behind(quiet_pipeline):
    """Finalize only claims and dispatches; the worker concatenates."""
    session = cast(ImageUploadSession, ImageUploadSessionFactory(destination_path="uploads/test/chunked.jp2"))
    tmp = services.session_tmp_dir(session)
    tmp.mkdir(parents=True, exist_ok=True)
    payload = tmp / "source.tif"
    Image.new("RGB", (20, 10), color="red").save(payload, format="TIFF")
    data = payload.read_bytes()
    session.declared_size, session.chunk_size = len(data), 1024
    session.received_chunks = list(range(session.total_chunks))
    session.status = ImageUploadSession.Status.ASSEMBLED
    session.save()
    for index in range(session.total_chunks):
        services.chunk_path(session, index).write_bytes(data[index * 1024 : (index + 1) * 1024])

    ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == ImageUploadSession.Status.COMPLETE
    assert (services.media_root() / session.destination_path).read_bytes() == b"jp2-bytes"


def test_never_overwrites_a_file_already_at_the_destination(quiet_pipeline):
    """A second session that won a race (or a stray file) must not be clobbered,
    and the failure path must not delete a file this run did not write."""
    session = _assembled_session()
    existing = services.media_root() / session.destination_path
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"someone else's image")

    with pytest.raises(ingest.IngestError, match="already exists"):
        ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == ImageUploadSession.Status.FAILED
    assert existing.read_bytes() == b"someone else's image"


def test_soft_time_limit_is_recorded_as_a_timeout(quiet_pipeline, monkeypatch):
    from celery.exceptions import SoftTimeLimitExceeded

    monkeypatch.setattr(ingest, "smoke_test_tile", MagicMock(side_effect=SoftTimeLimitExceeded()))
    session = _assembled_session()

    with pytest.raises(SoftTimeLimitExceeded):
        ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == ImageUploadSession.Status.FAILED
    assert "timed out" in session.error
    assert not (services.media_root() / session.destination_path).exists()


def test_jp2_source_is_placed_without_conversion(quiet_pipeline):
    session = _assembled_session(tmp_image_format="JPEG2000", filename="direct.jp2")
    uploaded = services.assembled_path(session).read_bytes()

    ingest.ingest_session(str(session.pk))

    # Passthrough: served bytes are the upload itself, not a conversion.
    served = (services.media_root() / session.destination_path).read_bytes()
    assert served == uploaded


def test_failed_tile_check_cleans_up_and_records_error(quiet_pipeline, monkeypatch):
    monkeypatch.setattr(ingest, "smoke_test_tile", MagicMock(side_effect=ingest.IngestError("tile 500")))
    session = _assembled_session()

    with pytest.raises(ingest.IngestError, match="tile 500"):
        ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == ImageUploadSession.Status.FAILED
    assert "tile 500" in session.error
    assert not (services.media_root() / session.destination_path).exists()
    assert not ItemImage.objects.filter(image=session.destination_path).exists()
    # The assembled source survives for a retry / postmortem until cleanup.
    assert services.assembled_path(session).exists()


def test_tile_check_reports_the_sipi_status_rather_than_a_connection_error(monkeypatch, settings):
    """urlopen RAISES on any non-2xx, so a 404 (identifier/prefix mismatch) or a
    500 (SIPI cannot decode the file — the issue-#114 failure this check exists
    to catch) used to arrive as 'could not be reached', pointing an operator at
    networking instead of the real cause."""
    import urllib.error

    settings.UPLOADS_SIPI_BASE_URL = "http://image_server:1024"

    def raise_404(*_args, **_kwargs):
        raise urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)

    monkeypatch.setattr(ingest.urllib.request, "urlopen", raise_404)

    with pytest.raises(ingest.IngestError, match=r"HTTP 404"):
        ingest.smoke_test_tile("uploads/item-part-1/f1r.jp2")


def test_unexpected_failure_does_not_leak_its_text_to_the_client(quiet_pipeline, monkeypatch):
    """`session.error` is serialized to the client. A curated IngestError is
    safe to show; anything else can carry internal paths or a traceback."""
    secret = "/app/storage/uploads_tmp/deadbeef/assembled.tif"
    monkeypatch.setattr(ingest, "smoke_test_tile", MagicMock(side_effect=OSError(secret)))
    session = _assembled_session()

    with pytest.raises(OSError):
        ingest.ingest_session(str(session.pk))

    session.refresh_from_db()
    assert session.status == ImageUploadSession.Status.FAILED
    assert secret not in session.error
    assert "operator" in session.error


def test_duplicate_destination_row_guard(quiet_pipeline):
    from apps.manuscripts.tests.factories import ItemImageFactory

    session = _assembled_session()
    ItemImageFactory(image=session.destination_path)

    with pytest.raises(ingest.IngestError, match="already references"):
        ingest.ingest_session(str(session.pk))
    session.refresh_from_db()
    assert session.status == ImageUploadSession.Status.FAILED


def test_undecodable_file_is_rejected_before_conversion(quiet_pipeline):
    session = ImageUploadSessionFactory(original_filename="fake.tif", destination_path="uploads/test/fake.jp2")
    source = services.assembled_path(session)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"this is not an image")
    session.status = ImageUploadSession.Status.ASSEMBLED
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
    session = ImageUploadSessionFactory()
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

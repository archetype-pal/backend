from collections import namedtuple
from datetime import timedelta
import hashlib
import io
from unittest.mock import MagicMock

from django.utils import timezone
import pytest

from apps.manuscripts.tests.factories import ItemPartFactory
from apps.uploads import services
from apps.uploads.models import UploadSession
from apps.uploads.tests.factories import UploadSessionFactory
from apps.users.tests.factories import SuperuserFactory

pytestmark = pytest.mark.django_db


def _create_session(**overrides):
    defaults = {
        "owner": SuperuserFactory(),
        "item_part": ItemPartFactory(),
        "filename": "f12r.tif",
        "size": 12,
    }
    defaults.update(overrides)
    return services.create_session(**defaults)


class TestCreateSession:
    def test_happy_path_computes_destination_and_defaults(self, small_chunks):
        session = _create_session()
        assert session.destination_path == f"uploads/item-part-{session.item_part_id}/f12r.jp2"
        assert session.status == UploadSession.Status.PENDING
        assert session.chunk_size == small_chunks
        assert session.total_chunks == 3
        assert services.session_tmp_dir(session).is_dir()

    def test_custom_subfolder_and_stem_sanitization(self):
        session = _create_session(filename="Añ ge__12 (v).png", subfolder="bl/add-32246")
        assert session.destination_path == "bl/add-32246/A-ge__12-v.jp2"

    @pytest.mark.parametrize(
        "filename",
        ["notes.txt", "no-extension", "../evil.tif", "a/b.tif", ".tif"],
    )
    def test_rejects_bad_filenames(self, filename):
        with pytest.raises(services.UploadError):
            _create_session(filename=filename)

    @pytest.mark.parametrize("subfolder", ["UPPER/case", "has..dots", "/leading", "trailing/", "a//b", "-dash"])
    def test_rejects_bad_subfolders(self, subfolder):
        with pytest.raises(services.UploadError):
            _create_session(subfolder=subfolder)

    def test_rejects_oversize_and_bad_sha(self, settings):
        settings.UPLOADS_MAX_BYTES = 10
        with pytest.raises(services.UploadError, match="upload limit"):
            _create_session(size=11)
        with pytest.raises(services.UploadError, match="hexadecimal"):
            _create_session(size=5, sha256="nothex")

    def test_conflict_with_existing_item_image_row(self):
        from apps.manuscripts.tests.factories import ItemImageFactory

        part = ItemPartFactory()
        ItemImageFactory(item_part=part, image=f"uploads/item-part-{part.pk}/f12r.jp2")
        with pytest.raises(services.UploadConflict, match="ItemImage already references"):
            _create_session(item_part=part)

    def test_conflict_with_file_on_disk(self, settings):
        part = ItemPartFactory()
        dest = services.media_root() / f"uploads/item-part-{part.pk}/f12r.jp2"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        with pytest.raises(services.UploadConflict, match="file already exists"):
            _create_session(item_part=part)

    def test_conflict_with_active_session(self):
        part = ItemPartFactory()
        _create_session(item_part=part)
        with pytest.raises(services.UploadConflict, match="Another upload session"):
            _create_session(item_part=part)

    def test_insufficient_disk_space(self, monkeypatch):
        usage = namedtuple("usage", "total used free")
        monkeypatch.setattr(services.shutil, "disk_usage", lambda _: usage(100, 90, 10))
        with pytest.raises(services.InsufficientStorage):
            _create_session(size=12)

    def test_unwritable_originals_root_fails_early_with_clear_message(self, settings, tmp_path):
        """The 'Permission denied at archive time' class must surface at
        session creation, before any byte is uploaded."""
        locked = tmp_path / "locked-originals"
        locked.mkdir()
        locked.chmod(0o555)
        settings.UPLOADS_ORIGINALS_DIR = str(locked)
        try:
            with pytest.raises(services.StorageUnavailable, match="originals archive.*not writable"):
                _create_session()
        finally:
            locked.chmod(0o755)

    def test_uncreatable_tmp_root_fails_early(self, settings, tmp_path):
        parent = tmp_path / "locked-parent"
        parent.mkdir()
        parent.chmod(0o555)
        settings.UPLOADS_TMP_DIR = str(parent / "uploads_tmp")
        try:
            with pytest.raises(services.StorageUnavailable, match="upload temp.*not writable"):
                _create_session()
        finally:
            parent.chmod(0o755)

    def test_writable_existing_subfolder_passes_even_if_media_root_is_not_writable(self, settings, tmp_path):
        """The check targets the deepest existing ancestor of the actual
        destination: a read-only corpus root must not block uploads whose
        subfolder tree is already writable (the dev/prod reality where
        media/ belongs to another user but media/uploads/ is opened up)."""
        media = tmp_path / "media"
        part_dir = media / "uploads" / "writable-part"
        part_dir.mkdir(parents=True)
        media.chmod(0o555)
        settings.MEDIA_ROOT = str(media)
        try:
            session = _create_session(subfolder="uploads/writable-part")
            assert session.destination_path == "uploads/writable-part/f12r.jp2"
        finally:
            media.chmod(0o755)


class TestChunks:
    def test_receive_out_of_range_and_wrong_size(self, small_chunks):
        session = _create_session()
        with pytest.raises(services.UploadError, match="out of range"):
            services.receive_chunk(session, 3, io.BytesIO(b"aaaa"))
        with pytest.raises(services.UploadError, match="exactly 4 bytes"):
            services.receive_chunk(session, 0, io.BytesIO(b"toolong"))
        with pytest.raises(services.UploadError, match="exactly 4 bytes"):
            services.receive_chunk(session, 0, io.BytesIO(b"ab"))

    def test_receive_is_idempotent_and_tracks_missing(self, small_chunks):
        session = _create_session()
        session = services.receive_chunk(session, 1, io.BytesIO(b"bbbb"))
        session = services.receive_chunk(session, 1, io.BytesIO(b"bbbb"))
        assert session.received_chunks == [1]
        assert session.missing_chunks() == [0, 2]
        assert session.status == UploadSession.Status.UPLOADING


class TestFinalize:
    def _upload_all(self, session, payload: bytes):
        for index in range(session.total_chunks):
            start = index * session.chunk_size
            session = services.receive_chunk(session, index, io.BytesIO(payload[start : start + session.chunk_size]))
        return session

    def test_missing_chunks_conflict(self, small_chunks):
        session = _create_session()
        with pytest.raises(services.UploadConflict, match="Missing chunks"):
            services.finalize_session(session)

    def test_sha_mismatch_marks_failed(self, small_chunks):
        session = _create_session(sha256="0" * 64)
        session = self._upload_all(session, b"abcdefgh1234")
        with pytest.raises(services.UploadError, match="Integrity check failed"):
            services.finalize_session(session)
        session.refresh_from_db()
        assert session.status == UploadSession.Status.FAILED
        assert not services.assembled_path(session).exists()

    def test_happy_path_assembles_verifies_and_dispatches(self, small_chunks, monkeypatch):
        payload = b"abcdefgh1234"
        session = _create_session(sha256=hashlib.sha256(payload).hexdigest())
        session = self._upload_all(session, payload)
        delay = MagicMock(return_value=MagicMock(id="task-123"))
        monkeypatch.setattr("apps.uploads.tasks.ingest_upload.delay", delay)

        session = services.finalize_session(session)

        assert session.status == UploadSession.Status.ASSEMBLED
        assert session.computed_sha256 == hashlib.sha256(payload).hexdigest()
        assert session.task_id == "task-123"
        assert services.assembled_path(session).read_bytes() == payload
        assert not services.chunk_path(session, 0).exists()
        delay.assert_called_once_with(str(session.pk))

    def test_finalize_twice_conflicts(self, small_chunks, monkeypatch):
        session = _create_session()
        session = self._upload_all(session, b"abcdefgh1234")
        monkeypatch.setattr("apps.uploads.tasks.ingest_upload.delay", MagicMock(return_value=MagicMock(id="t")))
        session = services.finalize_session(session)
        with pytest.raises(services.UploadConflict, match="cannot be finalized"):
            services.finalize_session(session)


class TestCleanup:
    def test_removes_stale_non_complete_sessions(self):
        stale = UploadSessionFactory()
        fresh = UploadSessionFactory()
        done = UploadSessionFactory(status=UploadSession.Status.COMPLETE)
        services.session_tmp_dir(stale).mkdir(parents=True, exist_ok=True)
        old = timezone.now() - timedelta(days=30)
        UploadSession.objects.filter(pk__in=[stale.pk, done.pk]).update(modified=old)

        removed = services.cleanup_stale_sessions(older_than_days=7)

        assert removed == 1
        assert not services.session_tmp_dir(stale).exists()
        remaining = set(UploadSession.objects.values_list("pk", flat=True))
        assert remaining == {fresh.pk, done.pk}

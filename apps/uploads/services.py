"""Application services for chunked image-upload sessions.

Views stay transport-only (house rule): all validation, path safety, chunk
bookkeeping, assembly, and Celery dispatch live here. Path rules mirror the
SIPI contract — the media-relative destination path IS the IIIF identifier,
so it is computed and collision-checked before any byte is accepted.
"""

import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any, BinaryIO

from django.conf import settings
from django.db import transaction

from apps.manuscripts.models import ItemImage, ItemPart
from apps.uploads.models import UploadSession

ALLOWED_EXTENSIONS: tuple[str, ...] = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".jp2")

# Free space required before accepting an upload: the assembled file plus a
# same-size original move plus the converted JP2 (≤ original for lossless).
DISK_HEADROOM_FACTOR = 2.5

_SUBFOLDER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadError(Exception):
    """Domain error; the view layer maps `status_code` (and `code`, when set)
    onto the response."""

    status_code = 400
    code = ""


class UploadConflict(UploadError):
    status_code = 409


class DestinationExists(UploadConflict):
    """The destination is permanently taken (file on disk / ItemImage row) —
    a true duplicate the client can present as 'already present'."""

    code = "destination_exists"


class DestinationBusy(UploadConflict):
    """Another user's (or an already-processing) session holds the
    destination — transient, NOT a duplicate."""

    code = "session_active"


class InsufficientStorage(UploadError):
    status_code = 507


class StorageUnavailable(UploadError):
    """A storage root exists but the service user cannot write to it —
    a deployment/permissions problem, not a client error."""

    status_code = 503


def media_root() -> Path:
    return Path(settings.MEDIA_ROOT).resolve()


def tmp_root() -> Path:
    return Path(settings.UPLOADS_TMP_DIR).resolve()


def originals_root() -> Path:
    return Path(settings.UPLOADS_ORIGINALS_DIR).resolve()


def session_tmp_dir(session: UploadSession) -> Path:
    return tmp_root() / str(session.id)


def chunk_path(session: UploadSession, index: int) -> Path:
    return session_tmp_dir(session) / f"{index:06d}.part"


def assembled_path(session: UploadSession) -> Path:
    suffix = Path(session.original_filename).suffix.lower()
    return session_tmp_dir(session) / f"assembled{suffix}"


def sanitize_stem(filename: str) -> str:
    """Filename stem reduced to SIPI-safe path characters."""
    stem = Path(filename).stem
    stem = _UNSAFE_STEM_RE.sub("-", stem).strip(".-")
    return stem


def _validate_filename(filename: str) -> str:
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise UploadError("Filename must be a plain file name without directories.")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(f"Unsupported file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}.")
    if not sanitize_stem(filename):
        raise UploadError("Filename has no usable characters.")
    return ext


def _validate_subfolder(subfolder: str) -> str:
    if not subfolder:
        return ""
    if not _SUBFOLDER_RE.match(subfolder):
        raise UploadError("Subfolder may only contain lowercase letters, digits, '-', '_' and single '/' separators.")
    return subfolder


def compute_destination_path(*, item_part_id: int, filename: str, subfolder: str) -> str:
    """Media-relative path of the served .jp2 (== the SIPI IIIF identifier)."""
    folder = subfolder or f"uploads/item-part-{item_part_id}"
    destination = f"{folder}/{sanitize_stem(filename)}.jp2"
    if len(destination) > 200:  # ItemImage.image / UploadSession.destination_path max_length
        raise UploadError("Destination path exceeds 200 characters; use a shorter filename or subfolder.")
    return destination


def _check_destination_free(destination: str) -> None:
    if (media_root() / destination).exists():
        raise DestinationExists(f"A file already exists at '{destination}'. Uploads never overwrite.")
    # ItemImage.image has no unique constraint, so the DB row check is the
    # only thing preventing two rows from claiming one file.
    if ItemImage.objects.filter(image=destination).exists():
        raise DestinationExists(f"An ItemImage already references '{destination}'.")


def _resolve_active_session_collision(
    *, destination: str, owner: Any, size: int, locus: str, tags: str
) -> UploadSession | None:
    """Handle an active session already targeting `destination`.

    A browser reload loses the client-side queue but not the server-side
    session, which would otherwise squat on the destination until stale-
    cleanup. Same owner + same declared size ⇒ hand the interrupted session
    back so the client resumes its missing chunks; same owner + different
    size ⇒ the user re-picked a different file, supersede the stale attempt;
    anything else is genuinely busy.
    """
    existing: UploadSession | None = (
        UploadSession.objects.filter(destination_path=destination, status__in=UploadSession.ACTIVE_STATUSES)
        .order_by("-created")
        .first()
    )
    if existing is None:
        return None
    resumable = existing.status in (UploadSession.Status.PENDING, UploadSession.Status.UPLOADING)
    if existing.owner_id != owner.id or not resumable:
        raise DestinationBusy(f"Another upload session is already targeting '{destination}'.")
    if existing.declared_size == size:
        # Refresh the descriptive metadata (the user may have corrected it on
        # retry) and let the client resume from `missing_chunks`.
        existing.locus = locus
        existing.tags = tags
        existing.save(update_fields=["locus", "tags", "modified"])
        return existing
    abort_session(existing)  # different bytes: replace the interrupted attempt
    return None


def archive_folder(item_part_id: int, subfolder: str) -> str:
    """Folder (relative) an upload's original is archived under — shared with
    the ingest pipeline so preflight checks the exact directory it will use."""
    return subfolder or f"uploads/item-part-{item_part_id}"


def _deepest_existing(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path


def _require_writable(label: str, target_dir: Path) -> None:
    """`mkdir -p target_dir` must be possible: the deepest existing ancestor
    has to be writable by the service user."""
    probe = _deepest_existing(target_dir)
    if not os.access(probe, os.W_OK | os.X_OK):
        raise StorageUnavailable(
            f"Cannot write to the {label} directory '{target_dir}': '{probe}' is not writable "
            f"by the service user. An operator must fix its ownership/permissions."
        )


def _check_writable_destinations(destination: str, original_folder: str) -> None:
    """Fail session creation early — with an actionable message — when any
    directory the pipeline will write to isn't creatable/writable. Without
    this the editor only finds out AFTER uploading and converting a whole
    file (the archive step '[Errno 13] Permission denied' class)."""
    _require_writable("upload temp", tmp_root())
    _require_writable("media destination", (media_root() / destination).parent)
    _require_writable("originals archive", originals_root() / original_folder)


def _check_disk_space(size: int) -> None:
    free = shutil.disk_usage(_deepest_existing(tmp_root())).free
    if free < size * DISK_HEADROOM_FACTOR:
        raise InsufficientStorage(
            f"Not enough disk space: need ~{int(size * DISK_HEADROOM_FACTOR)} bytes free, have {free}."
        )


def create_session(
    *,
    owner: Any,
    item_part: ItemPart,
    filename: str,
    size: int,
    sha256: str = "",
    locus: str = "",
    tags: str = "",
    subfolder: str = "",
) -> tuple[UploadSession, bool]:
    """Create (or resume) an upload session for one file.

    Returns `(session, created)` — `created=False` means an interrupted
    session for the same file was handed back for the client to resume.
    """
    _validate_filename(filename)
    subfolder = _validate_subfolder(subfolder)
    if size <= 0:
        raise UploadError("File size must be positive.")
    if size > settings.UPLOADS_MAX_BYTES:
        raise UploadError(f"File exceeds the {settings.UPLOADS_MAX_BYTES}-byte upload limit.")
    if sha256 and not _SHA256_RE.match(sha256.lower()):
        raise UploadError("sha256 must be 64 hexadecimal characters.")

    destination = compute_destination_path(item_part_id=item_part.pk, filename=filename, subfolder=subfolder)
    _check_destination_free(destination)
    resumed = _resolve_active_session_collision(destination=destination, owner=owner, size=size, locus=locus, tags=tags)
    if resumed is not None:
        return resumed, False
    _check_writable_destinations(destination, archive_folder(item_part.pk, subfolder))
    _check_disk_space(size)

    session: UploadSession = UploadSession.objects.create(
        owner=owner,
        item_part=item_part,
        original_filename=filename,
        declared_size=size,
        declared_sha256=sha256.lower(),
        chunk_size=settings.UPLOADS_CHUNK_SIZE,
        destination_path=destination,
        subfolder=subfolder,
        locus=locus,
        tags=tags,
    )
    session_tmp_dir(session).mkdir(parents=True, exist_ok=True)
    return session, True


def expected_chunk_bytes(session: UploadSession, index: int) -> int:
    if index < session.total_chunks - 1:
        return int(session.chunk_size)
    return int(session.declared_size) - int(session.chunk_size) * (session.total_chunks - 1)


def receive_chunk(session: UploadSession, index: int, stream: BinaryIO) -> UploadSession:
    if session.status not in (UploadSession.Status.PENDING, UploadSession.Status.UPLOADING):
        raise UploadConflict(f"Session is '{session.status}'; chunks are no longer accepted.")
    if index < 0 or index >= session.total_chunks:
        raise UploadError(f"Chunk index {index} out of range (0–{session.total_chunks - 1}).")

    expected = expected_chunk_bytes(session, index)
    target = chunk_path(session, index)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part.tmp")
    written = 0
    with open(partial, "wb") as out:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            written += len(block)
            if written > expected:
                break
            out.write(block)
    if written != expected:
        partial.unlink(missing_ok=True)
        raise UploadError(f"Chunk {index} must be exactly {expected} bytes; received {written}.")
    partial.replace(target)  # atomic: a chunk file is only ever complete

    with transaction.atomic():
        current: UploadSession = UploadSession.objects.get(pk=session.pk)
        if index not in current.received_chunks:
            current.received_chunks = sorted([*current.received_chunks, index])
        current.status = UploadSession.Status.UPLOADING
        current.save(update_fields=["received_chunks", "status", "modified"])
    return current


def finalize_session(session: UploadSession) -> UploadSession:
    """Assemble chunks, verify size + checksum, and dispatch the ingest task."""
    if session.status not in (UploadSession.Status.PENDING, UploadSession.Status.UPLOADING):
        raise UploadConflict(f"Session is '{session.status}'; it cannot be finalized.")
    missing = session.missing_chunks()
    if missing:
        raise UploadConflict(f"Missing chunks: {missing[:20]}{'…' if len(missing) > 20 else ''}")

    target = assembled_path(session)
    digest = hashlib.sha256()
    total = 0
    with open(target, "wb") as out:
        for index in range(session.total_chunks):
            with open(chunk_path(session, index), "rb") as part:
                while block := part.read(1024 * 1024):
                    digest.update(block)
                    total += len(block)
                    out.write(block)
    for index in range(session.total_chunks):
        chunk_path(session, index).unlink(missing_ok=True)

    computed = digest.hexdigest()
    if total != session.declared_size or (session.declared_sha256 and computed != session.declared_sha256):
        target.unlink(missing_ok=True)
        session.status = UploadSession.Status.FAILED
        session.error = (
            f"Integrity check failed: got {total} bytes / sha256 {computed}, "
            f"declared {session.declared_size} bytes / sha256 {session.declared_sha256 or '(none)'}."
        )
        session.save(update_fields=["status", "error", "modified"])
        raise UploadError(session.error)

    session.computed_sha256 = computed
    session.status = UploadSession.Status.ASSEMBLED
    session.save(update_fields=["computed_sha256", "status", "modified"])

    from apps.uploads.tasks import ingest_upload

    result = ingest_upload.delay(str(session.pk))
    session.task_id = result.id
    session.save(update_fields=["task_id", "modified"])
    return session


def abort_session(session: UploadSession) -> None:
    if session.status in (UploadSession.Status.PROCESSING,):
        raise UploadConflict("Session is being processed and can no longer be aborted.")
    shutil.rmtree(session_tmp_dir(session), ignore_errors=True)
    session.delete()


def cleanup_stale_sessions(*, older_than_days: int) -> dict[str, int]:
    """Reap upload temp storage in two sweeps, returning {'sessions', 'orphans'}.

    1. Sessions that never completed and haven't changed in `older_than_days`:
       delete the row and its temp dir.
    2. ORPHAN temp dirs — a directory under UPLOADS_TMP_DIR whose UUID name is not
       backed by any surviving session, older than the same threshold. The row is
       gone, so a session-only cleanup can never see these; without this sweep they
       leak forever. The age check (dir mtime) avoids racing a just-created dir.
    """
    from datetime import timedelta

    from django.utils import timezone

    cutoff = timezone.now() - timedelta(days=older_than_days)

    sessions_removed = 0
    stale = UploadSession.objects.filter(modified__lt=cutoff).exclude(status=UploadSession.Status.COMPLETE)
    for session in stale:
        shutil.rmtree(session_tmp_dir(session), ignore_errors=True)
        session.delete()
        sessions_removed += 1

    orphans_removed = 0
    root = tmp_root()
    if root.exists():
        # Recompute after sweep 1 so freshly-deleted sessions count as orphans if
        # their rmtree failed (belt-and-suspenders), and survivors are excluded.
        live_ids = {str(pk) for pk in UploadSession.objects.values_list("id", flat=True)}
        cutoff_ts = cutoff.timestamp()
        for child in root.iterdir():
            if not child.is_dir() or child.name in live_ids:
                continue
            try:
                too_old = child.stat().st_mtime < cutoff_ts
            except OSError:
                continue
            if too_old:
                shutil.rmtree(child, ignore_errors=True)
                orphans_removed += 1

    return {"sessions": sessions_removed, "orphans": orphans_removed}

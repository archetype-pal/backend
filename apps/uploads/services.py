"""Application services for chunked image-upload sessions.

Views stay transport-only (house rule): all validation, path safety, chunk
bookkeeping, assembly, and Celery dispatch live here. Path rules mirror the
SIPI contract — the media-relative destination path IS the IIIF identifier,
so it is computed and collision-checked before any byte is accepted.
"""

import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, BinaryIO
from uuid import uuid4

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.manuscripts.models import ItemImage, ItemPart
from apps.uploads.models import ImageUploadSession

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS: tuple[str, ...] = (".tif", ".tiff", ".jpg", ".jpeg", ".png", ".jp2")

# Free space required before accepting an upload, measured on the uploads tmp
# filesystem: the chunk files and the assembled copy coexist there until the
# assembly is moved into place. The converted JP2 is NOT covered — it lands
# under MEDIA_ROOT, and lossless JP2 from a JPEG-in-TIFF source (issue #114)
# can exceed the original.
DISK_HEADROOM_FACTOR = 2.0

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


def session_tmp_dir(session: ImageUploadSession) -> Path:
    return tmp_root() / str(session.id)


def chunk_path(session: ImageUploadSession, index: int) -> Path:
    return session_tmp_dir(session) / f"{index:06d}.part"


def assembled_path(session: ImageUploadSession) -> Path:
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


def sanitize_subfolder(subfolder: str) -> str:
    """User-chosen folder under `uploads/`, reduced to safe path segments."""
    segments = (_UNSAFE_STEM_RE.sub("-", part).strip(".-") for part in subfolder.replace("\\", "/").split("/"))
    return "/".join(part for part in segments if part)


def compute_destination_path(*, item_part_id: int, filename: str, subfolder: str = "") -> str:
    """Media-relative path of the served .jp2 (== the SIPI IIIF identifier)."""
    folder = sanitize_subfolder(subfolder) or f"item-part-{item_part_id}"
    destination = f"uploads/{folder}/{sanitize_stem(filename)}.jp2"
    if len(destination) > 200:  # ItemImage.image / ImageUploadSession.destination_path max_length
        raise UploadError("Destination path exceeds 200 characters; use a shorter filename.")
    return destination


def _check_destination_free(destination: str) -> None:
    if (media_root() / destination).exists():
        raise DestinationExists(f"A file already exists at '{destination}'. Uploads never overwrite.")
    # ItemImage.image has no unique constraint, so the DB row check is the
    # only thing preventing two rows from claiming one file.
    if ItemImage.objects.filter(image=destination).exists():
        raise DestinationExists(f"An ItemImage already references '{destination}'.")


def _supersede(existing: ImageUploadSession, destination: str) -> None:
    """Discard an interrupted attempt so the caller can create a fresh session."""
    try:
        abort_session(existing)
    except UploadConflict as exc:
        # It raced into assembled/processing; ingest owns it now. Report it as
        # the transient hold it is — the client keys on `session_active` to
        # tell that apart from a true duplicate.
        raise DestinationBusy(f"Another upload session is already targeting '{destination}'.") from exc


def _has_nothing_to_lose(existing: ImageUploadSession) -> bool:
    """Whether discarding `existing` cannot destroy work someone else did.

    Only consulted for a session belonging to a DIFFERENT user, where the
    alternative is holding the destination until `cleanup_stale_uploads` runs
    (up to `UPLOADS_STALE_AFTER_DAYS`, default 7).
    """
    # Both halves are equivalent today: `receive_chunk` appends to
    # `received_chunks` and flips the status to UPLOADING in one save, so
    # PENDING implies an empty list. Asserting both anyway is free and keeps
    # this honest if some future path ever sets one without the other.
    #
    # No time cushion deliberately. A chunk PUT can be in flight for a session
    # that still looks empty, and superseding then makes that PUT fail — but it
    # fails gracefully (`receive_chunk` resolves the row with `.filter().first()`,
    # so the client gets a 404 and re-creates), and a cushion would trade that
    # for a constant nobody can defend.
    return existing.status == ImageUploadSession.Status.PENDING and not existing.received_chunks


def _resolve_active_session_collision(
    *, destination: str, owner: Any, size: int, locus: str, tags: str
) -> ImageUploadSession | None:
    """Handle an active session already targeting `destination`.

    A browser reload loses the client-side queue but not the server-side
    session, which would otherwise squat on the destination until stale-
    cleanup. Same owner + same declared size ⇒ hand the interrupted session
    back so the client resumes its missing chunks; same owner + different
    size ⇒ the user re-picked a different file, supersede the stale attempt.

    A session belonging to someone ELSE is superseded only when discarding it
    cannot lose anything — otherwise the destination is genuinely busy, and an
    editor whose colleague closed a laptop would be blocked for days with no
    way to clear it.
    """
    existing: ImageUploadSession | None = (
        ImageUploadSession.objects.filter(destination_path=destination, status__in=ImageUploadSession.ACTIVE_STATUSES)
        .order_by("-created")
        .first()
    )
    if existing is None:
        return None
    resumable = existing.status in (ImageUploadSession.Status.PENDING, ImageUploadSession.Status.UPLOADING)
    if existing.owner_id != owner.id or not resumable:
        if resumable and _has_nothing_to_lose(existing):
            _supersede(existing, destination)
            return None
        raise DestinationBusy(f"Another upload session is already targeting '{destination}'.")
    if existing.declared_size == size:
        # Refresh the descriptive metadata (the user may have corrected it on
        # retry) and let the client resume from `missing_chunks`.
        existing.locus = locus
        existing.tags = tags
        existing.save(update_fields=["locus", "tags", "modified"])
        return existing
    _supersede(existing, destination)  # different bytes: replace the interrupted attempt
    return None


def _deepest_existing(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path


def _require_writable(label: str, target_dir: Path) -> None:
    """`mkdir -p target_dir` must be possible: the deepest existing ancestor
    has to be writable by the service user."""
    probe = _deepest_existing(target_dir)
    if not os.access(probe, os.W_OK | os.X_OK):
        # The absolute paths are for the operator's log, not the response body.
        logger.error("Upload %s directory '%s' is not writable by the service user ('%s')", label, target_dir, probe)
        raise StorageUnavailable(
            f"The {label} directory is not writable by the service user. "
            "An operator must fix its ownership/permissions (see the API log)."
        )


def _check_writable_destinations(destination: str) -> None:
    """Fail session creation early — with an actionable message — when a
    directory the pipeline will write to isn't creatable/writable. Without
    this the editor only finds out AFTER uploading and converting a whole
    file (the '[Errno 13] Permission denied' class)."""
    _require_writable("upload temp", tmp_root())
    _require_writable("media destination", (media_root() / destination).parent)


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
    locus: str = "",
    tags: str = "",
    subfolder: str = "",
) -> tuple[ImageUploadSession, bool]:
    """Create (or resume) an upload session for one file.

    Returns `(session, created)` — `created=False` means an interrupted
    session for the same file was handed back for the client to resume.
    """
    _validate_filename(filename)
    if size <= 0:
        raise UploadError("File size must be positive.")
    if size > settings.UPLOADS_MAX_BYTES:
        raise UploadError(f"File exceeds the {settings.UPLOADS_MAX_BYTES}-byte upload limit.")

    destination = compute_destination_path(item_part_id=item_part.pk, filename=filename, subfolder=subfolder)
    # Active sessions first: ingest writes the JP2 straight to its final path,
    # so during `processing` the file exists on disk while the upload is still
    # in flight — that must read as `session_active`, not `destination_exists`.
    resumed = _resolve_active_session_collision(destination=destination, owner=owner, size=size, locus=locus, tags=tags)
    if resumed is not None:
        return resumed, False
    _check_destination_free(destination)
    _check_writable_destinations(destination)
    _check_disk_space(size)

    try:
        with transaction.atomic():
            session: ImageUploadSession = ImageUploadSession.objects.create(
                owner=owner,
                item_part=item_part,
                original_filename=filename,
                declared_size=size,
                chunk_size=settings.UPLOADS_CHUNK_SIZE,
                destination_path=destination,
                locus=locus,
                tags=tags,
            )
    except IntegrityError as exc:
        # The lookup above is check-then-insert; the partial unique constraint
        # on (destination_path) over active statuses is what actually stops two
        # concurrent creates from both winning — and both ingesting.
        raise DestinationBusy(f"Another upload session is already targeting '{destination}'.") from exc
    session_tmp_dir(session).mkdir(parents=True, exist_ok=True)
    return session, True


def expected_chunk_bytes(session: ImageUploadSession, index: int) -> int:
    if index < session.total_chunks - 1:
        return int(session.chunk_size)
    return int(session.declared_size) - int(session.chunk_size) * (session.total_chunks - 1)


def receive_chunk(session: ImageUploadSession, index: int, stream: BinaryIO) -> ImageUploadSession:
    if session.status not in (ImageUploadSession.Status.PENDING, ImageUploadSession.Status.UPLOADING):
        raise UploadConflict(f"Session is '{session.status}'; chunks are no longer accepted.")
    if index < 0 or index >= session.total_chunks:
        raise UploadError(f"Chunk index {index} out of range (0–{session.total_chunks - 1}).")

    expected = expected_chunk_bytes(session, index)
    target = chunk_path(session, index)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Unique per-request temp file. Concurrent sends of the SAME chunk are
    # legal (the create-or-resume endpoint hands the same session to every
    # tab of the owner, so two tabs can race on one index); with a shared
    # temp path the loser's replace() raised FileNotFoundError (a 500).
    # Distinct temp files + atomic replace make duplicates last-writer-wins,
    # which is safe because both carry identical bytes for the destination.
    partial = target.parent / f"{target.name}.{uuid4().hex}.tmp"
    written = 0
    try:
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
            raise UploadError(f"Chunk {index} must be exactly {expected} bytes; received {written}.")
        partial.replace(target)  # atomic: a chunk file is only ever complete
    finally:
        partial.unlink(missing_ok=True)

    with transaction.atomic():
        # Row lock: (a) two different chunks landing at once must not lose an
        # index to a read-modify-write race, and (b) a session claimed by a
        # concurrent finalize must never be flipped back to 'uploading'
        # underneath the ingest pipeline.
        # .first(), not .get(): an abort can delete the row between the chunk
        # write above and this lock, and DoesNotExist would surface as a 500.
        current: ImageUploadSession | None = (
            ImageUploadSession.objects.select_for_update().filter(pk=session.pk).first()
        )
        if current is None:
            raise UploadConflict("Session was aborted while this chunk was in flight.")
        if current.status not in (ImageUploadSession.Status.PENDING, ImageUploadSession.Status.UPLOADING):
            raise UploadConflict(f"Session is '{current.status}'; chunks are no longer accepted.")
        if index not in current.received_chunks:
            current.received_chunks = sorted([*current.received_chunks, index])
        current.status = ImageUploadSession.Status.UPLOADING
        current.save(update_fields=["received_chunks", "status", "modified"])
    return current


def finalize_session(session: ImageUploadSession) -> ImageUploadSession:
    """Claim the session for ingest and dispatch the task.

    Deliberately O(1): the chunks are concatenated by the worker
    (`assemble_session`), not here. Copying a multi-GB file inside one HTTP
    request outlives nginx's proxy timeout, and the client then sees a failed
    finalize for an upload that is succeeding.

    Safe under concurrent calls for the same session (two tabs can hold it —
    see receive_chunk): an atomic status compare-and-swap picks exactly one
    winner to dispatch ingest; every other caller gets a 409.
    """
    if session.status not in (ImageUploadSession.Status.PENDING, ImageUploadSession.Status.UPLOADING):
        raise UploadConflict(f"Session is '{session.status}'; it cannot be finalized.")
    missing = session.missing_chunks()
    if missing:
        raise UploadConflict(f"Missing chunks: {missing[:20]}{'…' if len(missing) > 20 else ''}")

    # Atomic claim: exactly one concurrent finalize flips the status and owns
    # everything after this line. (.update() bypasses auto_now — set modified.)
    claimed = ImageUploadSession.objects.filter(
        pk=session.pk,
        status__in=(ImageUploadSession.Status.PENDING, ImageUploadSession.Status.UPLOADING),
    ).update(
        status=ImageUploadSession.Status.ASSEMBLED,
        modified=timezone.now(),
    )
    if not claimed:
        # The row may be gone, not just moved on: pending/uploading stay
        # abortable, so a cancel can land here. refresh_from_db() would raise
        # DoesNotExist — a 500 from the path whose whole job is a controlled 409.
        current = ImageUploadSession.objects.filter(pk=session.pk).values_list("status", flat=True).first()
        if current is None:
            raise UploadConflict("Session was aborted while it was being finalized.")
        raise UploadConflict(f"Session is '{current}'; it cannot be finalized.")
    session.refresh_from_db()

    from apps.uploads.tasks import ingest_upload

    try:
        result = ingest_upload.delay(str(session.pk))
    except Exception as exc:
        # The ASSEMBLED claim above has already landed, and `assembled` is the
        # one state no recovery path can reach: it is not in ABORTABLE_STATUSES
        # so a client DELETE 409s, and it makes `resumable` false so even the
        # OWNER gets DestinationBusy on a retry. A broker outage here would
        # therefore lock the filename until `cleanup_stale_uploads` ran, days
        # later. `failed` is abortable and outside ACTIVE_STATUSES, so it frees
        # the destination immediately and the client can simply upload again.
        ImageUploadSession.objects.filter(pk=session.pk, status=ImageUploadSession.Status.ASSEMBLED).update(
            status=ImageUploadSession.Status.FAILED,
            error="Could not queue processing for this upload. Please try again.",
            modified=timezone.now(),
        )
        logger.exception("Could not dispatch ingest for upload session %s", session.pk)
        raise UploadError("Could not queue processing for this upload. Please try again.") from exc
    session.task_id = result.id
    session.save(update_fields=["task_id", "modified"])
    return session


def assemble_session(session: ImageUploadSession) -> Path:
    """Concatenate the chunk files into `assembled_path(session)` and sweep them.

    Runs on the worker (see finalize_session). Idempotent: a run that already
    produced the assembled file and swept the chunks is a no-op; one that was
    interrupted between the two re-assembles from the chunks it still has.
    """
    target = assembled_path(session)
    chunks = [chunk_path(session, index) for index in range(session.total_chunks)]
    if target.exists() and not any(chunk.exists() for chunk in chunks):
        return target

    partial = target.parent / f"{target.name}.{uuid4().hex}.tmp"
    total = 0
    try:
        with open(partial, "wb") as out:
            for chunk in chunks:
                with open(chunk, "rb") as part:
                    while block := part.read(1024 * 1024):
                        total += len(block)
                        out.write(block)
    except FileNotFoundError as exc:
        partial.unlink(missing_ok=True)
        raise UploadError("A chunk file is missing; the upload must be sent again.") from exc
    # Per-chunk sizes are enforced on receipt, so `total` can only differ from
    # the declared size if a chunk file was damaged on disk after its PUT.
    if total != session.declared_size:
        partial.unlink(missing_ok=True)
        raise UploadError(f"Declared {session.declared_size} bytes, assembled {total}.")
    partial.replace(target)
    for chunk in chunks:
        chunk.unlink(missing_ok=True)
    return target


#: States a client may still discard. `assembled` and `processing` belong to the
#: ingest task and are deliberately absent — see abort_session.
ABORTABLE_STATUSES = (
    ImageUploadSession.Status.PENDING,
    ImageUploadSession.Status.UPLOADING,
    ImageUploadSession.Status.COMPLETE,
    ImageUploadSession.Status.FAILED,
)


def abort_session(session: ImageUploadSession) -> None:
    """Discard a session and its temp files.

    A guarded delete rather than a status check, and the delete comes first:
    `finalize_session` flips pending/uploading → `assembled` and only then
    dispatches ingest, so an abort that read the status a moment earlier could
    otherwise remove the row *after* the task was queued — leaving the worker
    to raise DoesNotExist, or sweeping the assembled file out from under a
    conversion that had already started. `assembled` and `processing` are the
    ingest task's to finish; a session stuck in either is reaped by
    `cleanup_stale_uploads`, not by a client DELETE.
    """
    deleted, _ = ImageUploadSession.objects.filter(pk=session.pk, status__in=ABORTABLE_STATUSES).delete()
    if not deleted:
        current = ImageUploadSession.objects.filter(pk=session.pk).values_list("status", flat=True).first()
        raise UploadConflict(f"Session is '{current or session.status}' and can no longer be aborted.")
    shutil.rmtree(session_tmp_dir(session), ignore_errors=True)


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

    from apps.manuscripts.services.media import delete_item_image_files

    sessions_removed = 0
    stale = ImageUploadSession.objects.filter(modified__lt=cutoff).exclude(status=ImageUploadSession.Status.COMPLETE)
    for session in stale:
        shutil.rmtree(session_tmp_dir(session), ignore_errors=True)
        session.delete()
        # A worker killed mid-conversion (OOM, hard time limit) leaves a partial
        # JP2 at the destination with no row behind it; unless it goes too, every
        # later upload of that filename is refused as `destination_exists`.
        delete_item_image_files(session.destination_path)
        sessions_removed += 1

    orphans_removed = 0
    root = tmp_root()
    if root.exists():
        # Recompute after sweep 1 so freshly-deleted sessions count as orphans if
        # their rmtree failed (belt-and-suspenders), and survivors are excluded.
        live_ids = {str(pk) for pk in ImageUploadSession.objects.values_list("id", flat=True)}
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
